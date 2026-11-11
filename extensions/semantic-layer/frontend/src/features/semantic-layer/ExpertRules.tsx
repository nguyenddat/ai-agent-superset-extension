import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertCircle, Ban, Check, ChevronRight, FolderPlus, LoaderCircle, Pencil, Plus, RotateCcw, Search,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { expertRulesApi, requestJson } from './api';
import {
  firstListed, GroupDeleteDialog, GroupDialog, GroupedList, GroupSelect, useGroupWorkspace,
} from './ConceptGroups';
import { takeConceptFocus } from './conceptFocus';
import { CreationOrigin } from './CreationOrigin';
import { completeConceptCreation, takeConceptRequest } from './creationRequest';
import type { ConceptRequest } from './creationRequest';
import { ExpertRuleEditor } from './ExpertRuleEditor';
import { FileTransfer } from './FileTransfer';
import type { ExpertRuleDraft } from './ExpertRuleEditor';
import { GroupSuggestions } from './GroupSuggestions';
import { conditionPhrase, expertRuleErrorMessage } from './expertRuleFormat';
import { formatTime } from './MetricDefinitionPanel';
import { ReviewDecisionDialog } from './ReviewDecisionDialog';
import type { ReviewDecisionText } from './ReviewDecisionDialog';
import type {
  ConceptGroup, ExpertRule, ExpertRuleAuditEntry, ExpertRuleDatasetOption, ExpertRuleList, ExpertRuleState,
} from './types';

const STATE_LABELS: Record<ExpertRuleState, string> = {
  draft: 'Chờ duyệt',
  approved: 'Đã duyệt',
  outdated: 'Hết hiệu lực',
  revoked: 'Đã thu hồi',
};

const STATE_ORDER: ExpertRuleState[] = ['draft', 'outdated', 'approved', 'revoked'];

const RULE_FILE_GUIDE = (
  <ul>
    <li>
      Mỗi dòng là một rule, khớp với rule đã có theo <code>name</code> (không phân biệt hoa thường);
      {' '}<code>dataset</code> là tên bảng và không đổi được sau khi tạo.
    </li>
    <li>
      <code>glossary_terms</code> là các thuật ngữ đã duyệt, cách nhau bằng <code>;</code>; metric của rule lấy từ các
      thuật ngữ đó.
    </li>
    <li>
      Trong một ô, mỗi dòng là một mục: <code>conditions</code> viết <code>&lt;cột&gt; | &lt;toán tử&gt; |
      &lt;giá trị&gt;</code> (giá trị đọc như JSON: <code>35</code>, <code>true</code>, <code>[&quot;A&quot;,
      &quot;B&quot;]</code>, còn lại là chữ); <code>exceptions</code> viết <code>&lt;khi nào&gt; =&gt; &lt;kết
      quả&gt;</code>; <code>examples</code> viết <code>&lt;câu hỏi&gt; =&gt; &lt;cách hiểu&gt;</code>.
    </li>
    <li>
      <code>group</code> trống là chưa phân nhóm; nhóm chưa có sẽ được tạo. Rule mới hoặc được sửa đều ở trạng thái chờ
      duyệt; chỉ đổi nhóm thì không cần duyệt lại.
    </li>
  </ul>
);

const AUDIT_LABELS: Record<ExpertRuleAuditEntry['action'], string> = {
  created: 'tạo rule',
  updated: 'sửa nội dung',
  approved: 'duyệt',
  revoked: 'thu hồi',
  moved: 'chuyển nhóm',
};

const AUDIT_CLASSES: Record<ExpertRuleAuditEntry['action'], string> = {
  created: 'is-candidate',
  updated: 'is-candidate',
  approved: 'is-approve',
  revoked: 'is-revoke',
  moved: 'is-definition',
};

type RuleDecision = 'approve' | 'revoke';

const DECISION_TEXT: Record<RuleDecision, ReviewDecisionText> = {
  approve: {
    title: 'Duyệt rule',
    description: 'Sau khi duyệt, rule được đưa vào semantic layer cho người dùng có quyền trên dataset.',
    reasonLabel: 'Ghi chú khi duyệt (không bắt buộc)',
    confirmLabel: 'Duyệt',
    reasonRequired: false,
  },
  revoke: {
    title: 'Thu hồi rule',
    description: 'Rule sẽ không được dùng nữa cho tới khi được sửa và duyệt lại.',
    reasonLabel: 'Lý do thu hồi (bắt buộc)',
    confirmLabel: 'Thu hồi',
    reasonRequired: true,
    destructive: true,
  },
};

const formatDate = (value: string | null) => formatTime(value).split(' ').pop() ?? '';

/** One line on who moved the rule into its current state, or what it needs next. */
function reviewSummary(rule: ExpertRule, viewerId: number | null, secondReviewerRequired: boolean): string {
  // Rules written before every rule had to build on a glossary term must be linked to one when next edited.
  if (rule.glossary_terms.length === 0 && rule.state !== 'revoked') return 'Chưa gắn thuật ngữ · sửa để gắn thuật ngữ';
  switch (rule.state) {
    case 'approved':
      return `Duyệt bởi ${rule.approver_name ?? '—'} · ${formatDate(rule.approved_at)}`;
    case 'draft':
      if (rule.author_id !== viewerId) return `Soạn bởi ${rule.author_name ?? '—'} · chờ duyệt`;
      return secondReviewerRequired ? 'Bạn đã soạn · cần một quản trị viên khác duyệt' : 'Bạn đã soạn · chờ duyệt';
    case 'outdated':
      return 'Metric hoặc thuật ngữ liên kết đã thay đổi · cần sửa và duyệt lại';
    default:
      return `Thu hồi bởi ${rule.revoker_name ?? '—'} · ${formatDate(rule.revoked_at)}`;
  }
}

function RuleHistory({ rule, revision }: { rule: ExpertRule; revision: number }) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<ExpertRuleAuditEntry[] | null>(null);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    if (!open) return undefined;
    let active = true;
    setEntries(null);
    setLoadError('');
    requestJson<{ audit: ExpertRuleAuditEntry[] }>(expertRulesApi.audit(rule.id), 'GET')
      .then(payload => { if (active) setEntries([...payload.audit].reverse()); })
      .catch(reason => {
        if (active) setLoadError(reason instanceof Error ? reason.message : 'Không tải được lịch sử.');
      });
    return () => { active = false; };
  }, [open, rule.id, revision]);

  return (
    <section className="sl-metrics-section">
      <button type="button" className="sl-metrics-disclosure" aria-expanded={open} onClick={() => setOpen(!open)}>
        <ChevronRight /> Lịch sử duyệt
      </button>
      {!open ? null : loadError ? (
        <div className="sl-metric-error" role="alert"><AlertCircle /> {loadError}</div>
      ) : entries === null ? (
        <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải lịch sử…</p>
      ) : (
          <ol className="sl-metrics-history">
            {entries.map((entry, index) => (
              // A move keeps the lifecycle version, so several entries can share version and action.
              <li key={`${entry.lifecycle_version}-${entry.action}-${index}`} className={AUDIT_CLASSES[entry.action]}>
                <div>
                  <strong>{entry.actor_name ?? 'Người dùng đã xoá'}</strong> {AUDIT_LABELS[entry.action]}
                  {entry.action === 'created' || entry.action === 'updated' ? ` (bản ${entry.revision})` : ''}
                </div>
                <time>{formatTime(entry.occurred_at)}</time>
                {entry.reason ? <blockquote>{entry.reason}</blockquote> : null}
              </li>
            ))}
          </ol>
        )}
    </section>
  );
}

function RuleDetail({ rule, groups, historyRevision, moving, readOnly, onMove }: {
  rule: ExpertRule;
  groups: ConceptGroup[];
  historyRevision: number;
  moving: boolean;
  readOnly: boolean;
  onMove: (groupId: number | null) => void;
}) {
  const columnName = (columnId: number) => rule.column_names[String(columnId)] ?? `#${columnId}`;
  const links = [...rule.glossary_terms.map(term => ({ ...term, kind: 'Thuật ngữ' })),
    ...rule.metrics.map(metric => ({ ...metric, kind: 'Metric' }))];
  return (
    <div className="sl-metrics-definition" role="tabpanel">
      <dl className="sl-metrics-facts">
        <div>
          <dt>Nhóm</dt>
          <dd>
            <GroupSelect
              groups={groups}
              groupId={rule.group?.id ?? null}
              disabled={moving}
              inline
              readOnly={readOnly}
              onChange={onMove}
            />
          </dd>
        </div>
      </dl>
      <section className="sl-metrics-section">
        <h4>Khi nào áp dụng</h4>
        <ul className="sl-rule-conditions">
          {rule.conditions.map((condition, index) => (
            <li key={index}>
              {index > 0 ? <span className="sl-rule-joiner">và</span> : null}
              {conditionPhrase(condition, columnName(condition.field_ref.column_dictionary_id))}
            </li>
          ))}
        </ul>
      </section>
      {rule.exceptions.length > 0 ? (
        <section className="sl-metrics-section">
          <h4>Ngoại lệ</h4>
          <ul className="sl-rule-pairs">
            {rule.exceptions.map((item, index) => (
              <li key={index}><span>Khi {item.when}</span><span>→ {item.outcome}</span></li>
            ))}
          </ul>
        </section>
      ) : null}
      <section className="sl-metrics-section">
        <h4>Câu hỏi mẫu</h4>
        <ul className="sl-rule-pairs">
          {rule.examples.map((item, index) => (
            <li key={index}><span>“{item.question}”</span><span className="sl-metric-muted">{item.intent}</span></li>
          ))}
        </ul>
      </section>
      {links.length > 0 ? (
        <section className="sl-metrics-section">
          <h4>Liên kết</h4>
          <div className="sl-metric-trial-field">
            {links.map(link => (
              <span key={`${link.kind}-${link.id}`} className="sl-metric-token is-static" title={link.kind}>
                {link.kind}: {link.name}
              </span>
            ))}
          </div>
        </section>
      ) : null}
      <RuleHistory rule={rule} revision={historyRevision} />
    </div>
  );
}

/**
 * A shared rule for a concept users defined for themselves: its name and a question users asked as the first example.
 * The conditions stay empty because the business's threshold is the expert's call, not the users' own sense.
 */
function draftFromRequest(request: ConceptRequest): ExpertRuleDraft {
  return {
    name: request.name,
    datasetId: null,
    glossaryTermIds: [],
    example: request.exampleQuestion ? { question: request.exampleQuestion, intent: '' } : null,
  };
}

/**
 * Admin workspace for expert rules: write a draft, have a second administrator approve it, revoke with a reason. A
 * Semantic Layer Viewer gets it `readOnly`, with every editing control hidden.
 */
export function ExpertRules({ readOnly = false }: { readOnly?: boolean }) {
  // Set when "Xử lý câu hỏi" sent the administrator here to cover a concept users defined for themselves.
  const [creation, setCreation] = useState<ConceptRequest | null>(() => takeConceptRequest('expert_rule'));
  const [ruleList, setRuleList] = useState<ExpertRuleList>(
    { rules: [], groups: [], current_user_id: null, require_second_reviewer: false },
  );
  const [datasets, setDatasets] = useState<ExpertRuleDatasetOption[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(() => takeConceptFocus('rules'));
  const [editing, setEditing] = useState<'new' | 'existing' | null>(creation ? 'new' : null);
  // The rule opened with 'Sửa': the form stays on it even when the search or filter hides it.
  const [editingRuleId, setEditingRuleId] = useState<number | null>(null);
  const [stateFilter, setStateFilter] = useState<ExpertRuleState | 'all'>('all');
  const [searchText, setSearchText] = useState('');
  const [loading, setLoading] = useState(true);
  const [openDecision, setOpenDecision] = useState<RuleDecision | null>(null);
  const [deciding, setDeciding] = useState(false);
  // Bumped after every change so an open history fetches the new events.
  const [historyRevision, setHistoryRevision] = useState(0);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [rules, options] = await Promise.all([
        requestJson<ExpertRuleList>(expertRulesApi.rules, 'GET'),
        requestJson<{ datasets: ExpertRuleDatasetOption[] }>(expertRulesApi.options, 'GET'),
      ]);
      setRuleList(rules);
      setDatasets(options.datasets);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không tải được danh sách rule.');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const groupWorkspace = useGroupWorkspace(
    { groups: expertRulesApi.groups, group: expertRulesApi.group }, load, setError,
  );
  const [moving, setMoving] = useState(false);

  const stateCounts = useMemo(() => {
    const counts = new Map<ExpertRuleState, number>();
    ruleList.rules.forEach(rule => counts.set(rule.state, (counts.get(rule.state) ?? 0) + 1));
    return counts;
  }, [ruleList]);
  const visibleRules = useMemo(() => {
    const query = searchText.trim().toLowerCase();
    return ruleList.rules.filter(rule => (
      (stateFilter === 'all' || rule.state === stateFilter) && (!query || rule.name.toLowerCase().includes(query))
    ));
  }, [ruleList, stateFilter, searchText]);
  const filtering = stateFilter !== 'all' || searchText.trim() !== '';
  const ruleGroupId = (rule: ExpertRule) => rule.group?.id ?? null;
  // The detail follows the list: a rule the search or filter hides is not shown, and the first listed rule opens.
  const selectedRule = visibleRules.find(rule => rule.id === selectedId)
    ?? firstListed(ruleList.groups, visibleRules, ruleGroupId);
  const stateItems = [
    { value: 'all', label: `Mọi trạng thái (${ruleList.rules.length})` },
    ...STATE_ORDER.map(state => ({ value: state, label: `${STATE_LABELS[state]} (${stateCounts.get(state) ?? 0})` })),
  ];

  const startNew = () => { setCreation(null); setEditing('new'); };
  const closeEditor = () => { setEditing(null); setCreation(null); };

  const refreshAfterChange = async (ruleId: number | null) => {
    if (ruleId !== null) setSelectedId(ruleId);
    await load();
    setHistoryRevision(revision => revision + 1);
  };

  const saveFromEditor = async (ruleId: number) => {
    if (creation) await completeConceptCreation(creation);
    closeEditor();
    await refreshAfterChange(ruleId);
  };

  const decide = async (decision: RuleDecision, reason: string) => {
    if (!selectedRule) return;
    const endpoint = (decision === 'approve' ? expertRulesApi.approve : expertRulesApi.revoke)(selectedRule.id);
    setDeciding(true);
    setError('');
    try {
      const body = { expected_revision: selectedRule.lifecycle_version, reason: reason || null };
      await requestJson(endpoint, 'POST', body);
      setOpenDecision(null);
      await refreshAfterChange(selectedRule.id);
    } catch (failure) {
      setOpenDecision(null);
      setError(expertRuleErrorMessage(failure instanceof Error ? failure.message : 'Thao tác không thành công.'));
    } finally {
      setDeciding(false);
    }
  };

  // A group only organizes rules, so a move takes effect at once and the rule keeps its approval.
  const moveRule = async (rule: ExpertRule, groupId: number | null) => {
    setMoving(true);
    setError('');
    try {
      await requestJson(expertRulesApi.move(rule.id), 'PUT', { group_id: groupId });
      await refreshAfterChange(rule.id);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Không chuyển được rule sang nhóm khác.');
    } finally {
      setMoving(false);
    }
  };

  const state = selectedRule?.state;
  const approvalBlocked = state === 'draft' && ruleList.require_second_reviewer
    && selectedRule?.author_id === ruleList.current_user_id;
  const editorRule = editing === 'existing' ? ruleList.rules.find(rule => rule.id === editingRuleId) ?? null : null;
  const isSelected = (rule: ExpertRule) => editing !== 'new' && selectedRule?.id === rule.id;

  return (
    <div className="sl-metrics">
      <aside className="sl-metrics-browser" aria-label="Danh sách rule">
        <div className="sl-metrics-browser-filters">
          <div className="sl-metrics-search">
            <Search />
            <Input
              aria-label="Tìm rule"
              placeholder="Tìm rule"
              value={searchText}
              onChange={event => setSearchText(event.target.value)}
            />
            <Button variant="ghost" size="icon" aria-label="Tải lại" disabled={loading} onClick={() => void load()}>
              {loading ? <LoaderCircle className="sl-spin" /> : <RotateCcw />}
            </Button>
          </div>
          <Select
            items={stateItems}
            value={stateFilter}
            onValueChange={value => setStateFilter(value as ExpertRuleState | 'all')}
          >
            <SelectTrigger aria-label="Lọc theo trạng thái" className="sl-metrics-filter-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
              <SelectGroup>
                {stateItems.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
              </SelectGroup>
            </SelectContent>
          </Select>
          {readOnly ? null : (
            <>
              <Button variant="outline" disabled={datasets.length === 0} onClick={() => startNew()}>
                <Plus data-icon="inline-start" /> Tạo rule
              </Button>
              <Button variant="outline" onClick={() => groupWorkspace.startEditing('new')}>
                <FolderPlus data-icon="inline-start" /> Tạo nhóm
              </Button>
              <GroupSuggestions
                noun="rule"
                endpoint={expertRulesApi.groupSuggestions}
                groups={ruleList.groups}
                errorMessage={expertRuleErrorMessage}
                onApplied={() => refreshAfterChange(null)}
              />
              <FileTransfer
                subject="rule"
                endpoint={expertRulesApi.file}
                guide={RULE_FILE_GUIDE}
                onImported={() => void refreshAfterChange(null)}
              />
            </>
          )}
        </div>
        <div className="sl-metrics-list">
          {loading && ruleList.rules.length === 0 ? (
            <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải rule…</p>
          ) : visibleRules.length === 0 && (filtering || readOnly || ruleList.groups.length === 0) ? (
            <p className="sl-metric-muted">
              {ruleList.rules.length > 0
                ? 'Không có rule nào khớp bộ lọc.'
                : readOnly
                  ? 'Chưa có rule nào bạn được xem. Rule chỉ hiện khi bạn có quyền đọc dataset của nó.'
                  : 'Chưa có rule nào. Bấm "Tạo rule" để bắt đầu.'}
            </p>
          ) : (
            <GroupedList
              noun="rule"
              groups={ruleList.groups}
              items={visibleRules}
              groupIdOf={ruleGroupId}
              filtered={filtering}
              onEditGroup={readOnly ? undefined : group => groupWorkspace.startEditing(group)}
              onDeleteGroup={readOnly ? undefined : groupWorkspace.setDeleting}
              renderItem={rule => (
                <button
                  key={rule.id}
                  type="button"
                  className={`sl-metrics-item${isSelected(rule) ? ' is-selected' : ''}`}
                  title={rule.dataset_name ?? 'Dataset đã xoá'}
                  onClick={() => { setSelectedId(rule.id); setEditing(null); }}
                >
                  <span className={`sl-metrics-dot is-${rule.state}`} title={STATE_LABELS[rule.state]} />
                  <span className="sl-metrics-item-name">{rule.name}</span>
                </button>
              )}
            />
          )}
        </div>
      </aside>
      <section className="sl-metrics-detail" aria-label="Chi tiết rule">
        {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
        {editing === 'new' && loading && datasets.length === 0 ? (
          <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải dataset…</p>
        ) : editing === 'new' || (editing === 'existing' && editorRule) ? (
          <>
            <header className="sl-metrics-detail-heading is-editing">
              <div className="sl-metrics-title">
                <h3>{editorRule ? `Sửa: ${editorRule.name}` : 'Rule mới'}</h3>
                <p>Lưu xong, rule ở trạng thái chờ duyệt và chỉ có hiệu lực sau khi được duyệt.</p>
              </div>
            </header>
            {creation && !editorRule ? (
              <CreationOrigin request={creation}>
                <p>Thêm điều kiện bên dưới theo ngưỡng chính thức của nghiệp vụ.</p>
              </CreationOrigin>
            ) : null}
            <ExpertRuleEditor
              key={editorRule?.id ?? 'new'}
              rule={editorRule}
              draft={creation && !editorRule ? draftFromRequest(creation) : null}
              datasets={datasets}
              groups={ruleList.groups}
              onCancel={closeEditor}
              onSaved={ruleId => void saveFromEditor(ruleId)}
            />
          </>
        ) : !selectedRule ? (
          <p className="sl-metric-muted sl-rule-empty">
            {!readOnly && datasets.length === 0 && !loading
              ? 'Cần ít nhất một dataset có Data Dictionary để viết rule.'
              : 'Chọn một rule để xem chi tiết.'}
          </p>
        ) : (
          <>
            <header className="sl-metrics-detail-heading">
              <div className="sl-metrics-title">
                <h3>
                  {selectedRule.name}{' '}
                  <span className={`sl-metric-state is-${selectedRule.state}`}>{STATE_LABELS[selectedRule.state]}</span>
                </h3>
                <p>
                  {selectedRule.dataset_name}
                  {' · '}
                  {reviewSummary(selectedRule, ruleList.current_user_id, ruleList.require_second_reviewer)}
                </p>
              </div>
              {readOnly ? null : (
                <div className="sl-metrics-actions">
                  <Button
                    variant="outline"
                    disabled={deciding}
                    onClick={() => { setEditingRuleId(selectedRule.id); setEditing('existing'); }}
                  >
                    <Pencil data-icon="inline-start" /> Sửa
                  </Button>
                  {state === 'draft' ? (
                    <Button
                      disabled={deciding || approvalBlocked}
                      title={approvalBlocked ? 'Người soạn rule không thể tự duyệt.' : undefined}
                      onClick={() => setOpenDecision('approve')}
                    >
                      <Check data-icon="inline-start" /> Duyệt
                    </Button>
                  ) : null}
                  {state === 'approved' || state === 'outdated' ? (
                    <Button variant="outline" disabled={deciding} onClick={() => setOpenDecision('revoke')}>
                      <Ban data-icon="inline-start" /> Thu hồi
                    </Button>
                  ) : null}
                </div>
              )}
            </header>
            <RuleDetail
              key={selectedRule.id}
              rule={selectedRule}
              groups={ruleList.groups}
              historyRevision={historyRevision}
              moving={moving}
              readOnly={readOnly}
              onMove={groupId => void moveRule(selectedRule, groupId)}
            />
          </>
        )}
      </section>
      <ReviewDecisionDialog
        text={openDecision === null ? null : DECISION_TEXT[openDecision]}
        subject={selectedRule?.name ?? ''}
        reasonMaxLength={512}
        busy={deciding}
        onConfirm={reason => { if (openDecision) void decide(openDecision, reason); }}
        onClose={() => setOpenDecision(null)}
      />
      <GroupDialog
        noun="rule"
        editing={groupWorkspace.editing}
        busy={groupWorkspace.busy}
        error={groupWorkspace.dialogError ? expertRuleErrorMessage(groupWorkspace.dialogError) : ''}
        onSave={values => void groupWorkspace.save(values)}
        onClose={() => groupWorkspace.startEditing(null)}
      />
      <GroupDeleteDialog
        noun="rule"
        group={groupWorkspace.deleting}
        memberCount={ruleList.rules.filter(rule => rule.group?.id === groupWorkspace.deleting?.id).length}
        busy={groupWorkspace.busy}
        onConfirm={() => void groupWorkspace.remove()}
        onClose={() => groupWorkspace.setDeleting(null)}
      />
    </div>
  );
}
