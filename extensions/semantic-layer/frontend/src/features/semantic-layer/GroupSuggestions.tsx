import React, { useState } from 'react';
import { AlertCircle, Check, LoaderCircle, Sparkles, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { requestJson } from './api';
import type { GroupNoun } from './ConceptGroups';
import { OptionSelect } from './ExpertRuleEditor';
import type { ConceptGroup, GroupSuggestion, GroupSuggestionList } from './types';

const NEW_GROUP = 'new';

const percent = (similarity: number) => `${Math.round(similarity * 100)}%`;

type SuggestionCardProps = {
  noun: GroupNoun;
  suggestion: GroupSuggestion;
  groups: ConceptGroup[];
  busy: boolean;
  onApply: (memberIds: number[], target: { group_id: number } | { group_name: string }) => void;
  onDismiss: () => void;
};

/** One suggestion the administrator may take as it is, change (group, name, members) or dismiss. */
function SuggestionCard({ noun, suggestion, groups, busy, onApply, onDismiss }: SuggestionCardProps) {
  const [target, setTarget] = useState(suggestion.group ? String(suggestion.group.id) : NEW_GROUP);
  // A suggestion for an existing group proposes that group's name, which a new group could not take.
  const [groupName, setGroupName] = useState(suggestion.group ? '' : suggestion.proposed_name);
  const [memberIds, setMemberIds] = useState(() => suggestion.members.map(member => member.id));
  const toggle = (memberId: number) => setMemberIds(current => (
    current.includes(memberId) ? current.filter(id => id !== memberId) : [...current, memberId]
  ));
  const targetItems = [
    { value: NEW_GROUP, label: 'Nhóm mới' },
    ...groups.map(group => ({ value: String(group.id), label: group.name })),
  ];
  const ready = memberIds.length > 0 && (target !== NEW_GROUP || groupName.trim() !== '');

  return (
    <section className="sl-group-suggestion">
      <div className="sl-group-suggestion-target">
        <OptionSelect label="Đưa vào nhóm" items={targetItems} value={target} disabled={busy} onChange={setTarget} />
        {target === NEW_GROUP ? (
          <Input
            aria-label="Tên nhóm mới"
            placeholder="Tên nhóm mới"
            value={groupName}
            maxLength={255}
            disabled={busy}
            onChange={event => setGroupName(event.target.value)}
          />
        ) : null}
      </div>
      {suggestion.group_members.length > 0 ? (
        <p className="sl-metric-muted">
          Đã có trong nhóm: {suggestion.group_members.map(member => member.name).join(', ')}
        </p>
      ) : null}
      <ul className="sl-group-suggestion-members">
        {suggestion.members.map(member => (
          <li key={member.id}>
            <label>
              <Checkbox
                checked={memberIds.includes(member.id)}
                disabled={busy}
                onCheckedChange={() => toggle(member.id)}
              />
              <span>{member.name}</span>
              <span className="sl-metric-muted">
                giống «{member.closest.name}» {percent(member.closest.similarity)}
              </span>
            </label>
          </li>
        ))}
      </ul>
      <div className="sl-group-suggestion-actions">
        <Button variant="ghost" size="sm" disabled={busy} onClick={onDismiss}>
          <X data-icon="inline-start" /> Bỏ qua
        </Button>
        <Button
          size="sm"
          disabled={busy || !ready}
          title={memberIds.length === 0 ? `Chọn ít nhất một ${noun}.` : undefined}
          onClick={() => onApply(
            memberIds, target === NEW_GROUP ? { group_name: groupName.trim() } : { group_id: Number(target) },
          )}
        >
          <Check data-icon="inline-start" /> Áp dụng
        </Button>
      </div>
    </section>
  );
}

type GroupSuggestionsProps = {
  noun: GroupNoun;
  /** The suggestion list; `/apply` and `/dismiss` below it take the administrator's decision. */
  endpoint: string;
  groups: ConceptGroup[];
  /** Turns a server message into the page's wording; the expert rule page translates its validation messages. */
  errorMessage?: (message: string) => string;
  onApplied: () => Promise<void>;
};

/**
 * "Gợi ý gom nhóm": ungrouped terms or rules close in meaning, each suggested for a new group or an existing one.
 * Applying moves the ticked members without review; a dismissed suggestion is not offered again unchanged.
 */
export function GroupSuggestions({ noun, endpoint, groups, errorMessage, onApplied }: GroupSuggestionsProps) {
  const [open, setOpen] = useState(false);
  const [list, setList] = useState<GroupSuggestionList | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const run = async (action: () => Promise<void>, fallback: string) => {
    setBusy(true);
    setError('');
    try {
      await action();
      setList(await requestJson<GroupSuggestionList>(endpoint, 'GET'));
    } catch (failure) {
      const message = failure instanceof Error ? failure.message : fallback;
      setError(errorMessage ? errorMessage(message) : message);
    } finally {
      setBusy(false);
    }
  };
  const start = () => {
    setOpen(true);
    setList(null);
    void run(async () => undefined, 'Không tải được gợi ý gom nhóm.');
  };
  const apply = (memberIds: number[], target: { group_id: number } | { group_name: string }) => void run(
    async () => {
      await requestJson(`${endpoint}/apply`, 'POST', { member_ids: memberIds, ...target });
      await onApplied();
    },
    'Không áp dụng được gợi ý.',
  );
  const dismiss = (suggestion: GroupSuggestion) => void run(
    async () => { await requestJson(`${endpoint}/dismiss`, 'POST', { fingerprint: suggestion.fingerprint }); },
    'Không bỏ qua được gợi ý.',
  );

  return (
    <>
      <Button variant="outline" onClick={start}>
        <Sparkles data-icon="inline-start" /> Gợi ý gom nhóm
      </Button>
      {!open ? null : (
        <Dialog open onOpenChange={next => { if (!next && !busy) setOpen(false); }}>
          <DialogContent className="sm:max-w-2xl">
            <DialogHeader>
              <DialogTitle>Gợi ý gom nhóm {noun}</DialogTitle>
              <DialogDescription>
                {list?.method === 'tfidf'
                  ? `So sánh theo từ ngữ trùng nhau vì chưa dùng được mô hình embedding (ngưỡng ${list.threshold}).`
                  : list ? `So sánh nghĩa bằng mô hình ${list.model} (ngưỡng ${list.threshold}).` : null}
                {' '}Đổi nhóm, tên hoặc bỏ chọn {noun} trước khi áp dụng; chuyển nhóm không cần duyệt lại.
              </DialogDescription>
            </DialogHeader>
            {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
            {list === null ? (
              <p className="sl-metric-muted" hidden={!busy}><LoaderCircle className="sl-spin" /> Đang tìm gợi ý…</p>
            ) : list.suggestions.length === 0 ? (
              <p className="sl-metric-muted">Không có gợi ý nào: các {noun} chưa phân nhóm đều khác nghĩa nhau.</p>
            ) : (
              <div className="sl-group-suggestions">
                {list.suggestions.map(suggestion => (
                  <SuggestionCard
                    key={suggestion.fingerprint}
                    noun={noun}
                    suggestion={suggestion}
                    groups={groups}
                    busy={busy}
                    onApply={apply}
                    onDismiss={() => dismiss(suggestion)}
                  />
                ))}
              </div>
            )}
            <DialogFooter>
              <Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>Đóng</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
