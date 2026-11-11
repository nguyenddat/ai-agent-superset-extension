import React, { useCallback, useEffect, useState } from 'react';
import { AlertCircle, CheckCheck, EyeOff, LoaderCircle, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { requestJson, semanticLayerApi } from './api';
import { openConcept } from './conceptFocus';
import { formatTime } from './MetricDefinitionPanel';
import { ReviewDecisionDialog } from './ReviewDecisionDialog';
import type { Contradiction, ContradictionCheck, ContradictionItem, ContradictionKind } from './types';

const KIND_LABELS: Record<ContradictionKind, string> = {
  term_name_clash: 'Hai thuật ngữ trùng tên hoặc từ đồng nghĩa',
  rule_conditions_empty: 'Điều kiện của rule không thể cùng đúng',
  rule_rule_same_term: 'Hai rule cùng thuật ngữ nhưng khác điều kiện',
  rule_rule_overlap: 'Hai rule khác thuật ngữ nhưng điều kiện chồng lấn',
  rule_term_threshold: 'Ngưỡng của rule khác định nghĩa thuật ngữ',
  rule_example_threshold: 'Câu hỏi mẫu khác điều kiện của rule',
  term_term_meaning: 'Định nghĩa hai thuật ngữ trái nhau',
  term_metric_meaning: 'Định nghĩa thuật ngữ khác công thức metric',
  rule_term_meaning: 'Rule trái định nghĩa thuật ngữ',
  rule_rule_meaning: 'Ngoại lệ hoặc câu hỏi mẫu của hai rule trái nhau',
};

const ITEM_LABELS: Record<ContradictionItem['type'], string> = { term: 'Thuật ngữ', rule: 'Rule', metric: 'Metric' };

const DISMISS_TEXT = {
  title: 'Bỏ qua mâu thuẫn',
  description: 'Mâu thuẫn được giữ là đã bỏ qua cho tới khi một trong hai nội dung được sửa.',
  reasonLabel: 'Lý do bỏ qua (bắt buộc)',
  confirmLabel: 'Bỏ qua',
  reasonRequired: true,
};

// The server's model calls give up within about 90 seconds; past this the screen stops waiting for the AI step.
const AI_STEP_TIMEOUT_MS = 100_000;
const AI_STEP_TIMEOUT_MESSAGE = 'AI chưa trả lời kịp; các cặp chưa kiểm tra sẽ được kiểm tra ở lần sau.';

const KIND_ORDER = Object.keys(KIND_LABELS);

const itemNames = (contradiction: Contradiction) => contradiction.items.map(item => item.name).join(' ↔ ');

/** The server's order: open contradictions first, then dismissed ones, each by kind. */
function reviewOrder(contradictions: Contradiction[]): Contradiction[] {
  return [...contradictions].sort((first, second) => (
    Number(first.status !== 'open') - Number(second.status !== 'open')
    || KIND_ORDER.indexOf(first.kind) - KIND_ORDER.indexOf(second.kind)
    || first.id - second.id
  ));
}

/** The request's answer, or an error once `milliseconds` pass without one. */
async function withTimeout<T>(request: Promise<T>, milliseconds: number, message: string): Promise<T> {
  let timer = 0;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = window.setTimeout(() => reject(new Error(message)), milliseconds);
  });
  try {
    return await Promise.race([request, timeout]);
  } finally {
    window.clearTimeout(timer);
  }
}

/** What the list shows next to a kind: a dismissal, or that the AI model judged it. */
function listBadge(contradiction: Contradiction): string {
  if (contradiction.status === 'dismissed') return 'Đã bỏ qua';
  return contradiction.found_by === 'ai' ? 'AI' : '';
}

function ItemLink({ item }: { item: ContradictionItem }) {
  const label = `${ITEM_LABELS[item.type]}: ${item.name}`;
  if (item.type === 'metric') return <span>{label}</span>;
  const module = item.type === 'term' ? 'glossary' : 'rules';
  return (
    <Button variant="link" className="h-auto p-0" onClick={() => openConcept({ module, id: item.id })}>
      {label}
    </Button>
  );
}

function ContradictionDetail({ contradiction, busy, onDismiss }: {
  contradiction: Contradiction;
  busy: boolean;
  onDismiss: () => void;
}) {
  const open = contradiction.status === 'open';
  return (
    <>
      <header className="sl-metrics-detail-heading">
        <div className="sl-metrics-title">
          <h3>{KIND_LABELS[contradiction.kind]}</h3>
          <p>
            <span className={`sl-proposal-status${open ? '' : ' is-dismissed'}`}>
              {open ? 'Chưa xử lý' : 'Đã bỏ qua'}
            </span>
            {contradiction.found_by === 'ai' ? 'AI đánh giá' : 'Phát hiện bằng quy tắc'}
            {' · '}{formatTime(contradiction.detected_at)}
          </p>
        </div>
        {open ? (
          <div className="sl-metrics-actions">
            <Button variant="outline" disabled={busy} onClick={onDismiss}>
              <EyeOff data-icon="inline-start" /> Bỏ qua
            </Button>
          </div>
        ) : null}
      </header>
      <div className="sl-metrics-definition">
        {open ? null : (
          <p className="sl-proposal-note">
            Bỏ qua bởi {contradiction.dismissed_by_name ?? '—'} · {formatTime(contradiction.dismissed_at)}:{' '}
            {contradiction.dismiss_reason}
          </p>
        )}
        <section className="sl-metrics-section">
          <h4>Nội dung liên quan</h4>
          <div className="sl-contradiction-items">
            {contradiction.items.map(item => <ItemLink key={`${item.type}-${item.id}`} item={item} />)}
          </div>
        </section>
        <section className="sl-metrics-section">
          <h4>{contradiction.found_by === 'ai' ? 'Nội dung AI đã đọc' : 'Bằng chứng'}</h4>
          <ul className="sl-definition-review-list">
            {contradiction.evidence.map(line => <li key={line} className="sl-definition-review-text">{line}</li>)}
          </ul>
        </section>
        <section className="sl-metrics-section">
          <h4>{contradiction.found_by === 'ai' ? 'Nhận định của AI' : 'Vì sao mâu thuẫn'}</h4>
          <p className="sl-glossary-definition">{contradiction.explanation}</p>
        </section>
      </div>
    </>
  );
}

/**
 * Contradictions between glossary terms, expert rules and the metrics terms link, found automatically. Opening the
 * view checks the current content again: the rule-based findings first, then the AI model's, which may take a while.
 * An administrator opens the items to fix them, or dismisses a contradiction with a reason until either item changes.
 */
export function Contradictions() {
  const [result, setResult] = useState<ContradictionCheck | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [checking, setChecking] = useState(true);
  // Pairs the AI step is judging now; 0 when it is not running.
  const [aiPairs, setAiPairs] = useState(0);
  const [dismissing, setDismissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const check = useCallback(async () => {
    setChecking(true);
    try {
      const ruleCheck = await requestJson<ContradictionCheck>(
        semanticLayerApi.contradictionsCheck, 'POST', { rules_only: true },
      );
      setResult(ruleCheck);
      setError('');
      if (ruleCheck.semantic.status === 'deferred') {
        setAiPairs(ruleCheck.semantic.unchecked);
        const aiCheck = requestJson<ContradictionCheck>(semanticLayerApi.contradictionsCheck, 'POST', {});
        setResult(await withTimeout(aiCheck, AI_STEP_TIMEOUT_MS, AI_STEP_TIMEOUT_MESSAGE));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không kiểm tra được mâu thuẫn.');
    }
    setAiPairs(0);
    setChecking(false);
  }, []);
  useEffect(() => { void check(); }, [check]);

  const contradictions = result?.contradictions ?? [];
  const selected = contradictions.find(item => item.id === selectedId) ?? contradictions[0] ?? null;
  const openCount = contradictions.filter(item => item.status === 'open').length;
  const CheckIcon = checking ? LoaderCircle : RotateCcw;

  const dismiss = async (reason: string) => {
    if (!selected) return;
    setBusy(true);
    try {
      const { contradiction } = await requestJson<{ contradiction: Contradiction }>(
        semanticLayerApi.contradictionDismiss(selected.id), 'POST', { reason },
      );
      setResult(current => current && {
        ...current,
        contradictions: reviewOrder(
          current.contradictions.map(item => (item.id === contradiction.id ? contradiction : item)),
        ),
      });
      setDismissing(false);
      setError('');
    } catch (reason) {
      // Close the dialog so the error shows, as Glossary and Expert Rules do.
      setDismissing(false);
      setError(reason instanceof Error ? reason.message : 'Không bỏ qua được mâu thuẫn.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sl-metrics sl-question-review">
      <aside className="sl-metrics-browser" aria-label="Danh sách mâu thuẫn">
        <div className="sl-metrics-browser-filters">
          <div className="sl-metrics-search">
            <span className="sl-proposal-count">{result ? `${openCount} mâu thuẫn chưa xử lý` : ''}</span>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Kiểm tra lại"
              title="Kiểm tra lại"
              disabled={checking}
              onClick={() => void check()}
            >
              <CheckIcon className={checking ? 'sl-spin' : undefined} />
            </Button>
          </div>
        </div>
        <div className="sl-metrics-list">
          {result === null ? (
            checking ? (
              <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang kiểm tra thuật ngữ và rule…</p>
            ) : (
              <p className="sl-metric-muted sl-question-list-empty">
                Chưa kiểm tra được mâu thuẫn; bấm “Kiểm tra lại” để thử lại.
              </p>
            )
          ) : contradictions.length === 0 ? (
            <p className="sl-metric-muted sl-question-list-empty">
              {aiPairs ? 'Quy tắc chưa phát hiện mâu thuẫn nào; đang chờ AI.' : 'Không phát hiện mâu thuẫn nào.'}
            </p>
          ) : contradictions.map(contradiction => (
            <button
              key={contradiction.id}
              type="button"
              className={`sl-metrics-item sl-question-item${selected?.id === contradiction.id ? ' is-selected' : ''}`}
              onClick={() => setSelectedId(contradiction.id)}
            >
              <span className="sl-question-item-text">{itemNames(contradiction)}</span>
              <span className="sl-question-item-meta">
                {KIND_LABELS[contradiction.kind]}
                <span className="sl-contradiction-badge">{listBadge(contradiction)}</span>
              </span>
            </button>
          ))}
        </div>
      </aside>
      <section className="sl-metrics-detail" aria-label="Chi tiết mâu thuẫn">
        {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
        {aiPairs ? (
          <p className="sl-proposal-note sl-contradiction-notice">
            <LoaderCircle className="sl-spin" /> AI đang kiểm tra {aiPairs} cặp nội dung về nghĩa, có thể mất tới một
            phút. Mâu thuẫn tìm bằng quy tắc đã có trong danh sách.
          </p>
        ) : result?.semantic.message ? (
          <div className="sl-metric-warning sl-contradiction-notice" role="note">
            <AlertCircle /> {result.semantic.message}
          </div>
        ) : null}
        {selected ? (
          <ContradictionDetail contradiction={selected} busy={busy} onDismiss={() => setDismissing(true)} />
        ) : result && !aiPairs ? (
          <div className="sl-question-empty">
            <CheckCheck aria-hidden="true" />
            <p>Thuật ngữ và rule đang dùng không nói trái nhau.</p>
          </div>
        ) : null}
      </section>
      <ReviewDecisionDialog
        text={dismissing ? DISMISS_TEXT : null}
        subject={selected ? itemNames(selected) : ''}
        reasonMaxLength={512}
        busy={busy}
        onConfirm={reason => void dismiss(reason)}
        onClose={() => setDismissing(false)}
      />
    </div>
  );
}
