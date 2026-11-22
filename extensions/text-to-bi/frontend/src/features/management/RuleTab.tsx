import React, { useEffect, useMemo, useState } from 'react';
import { PlusIcon, ScaleIcon, Trash2Icon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

import { managementApi } from './api';
import type { Access, Condition, MetricRef, Rule, RuleInput, RuleOptions } from './types';

const operators = [
  ['equals', 'Bằng'], ['not_equals', 'Khác'], ['contains', 'Chứa'], ['not_contains', 'Không chứa'],
  ['greater_than', 'Lớn hơn'], ['greater_than_or_equal', 'Lớn hơn hoặc bằng'],
  ['less_than', 'Nhỏ hơn'], ['less_than_or_equal', 'Nhỏ hơn hoặc bằng'],
  ['in', 'Trong tập'], ['not_in', 'Ngoài tập'], ['is_null', 'Rỗng'], ['is_not_null', 'Không rỗng'],
] as const;

const emptyCondition = (columnName = ''): Condition => ({
  column_name: columnName, operator: 'equals', value_type: 'string', value: '',
});
const blank = (datasetId: number, columnName = ''): RuleInput => ({
  dataset_id: datasetId, name: '', description: null, conditions: [emptyCondition(columnName)],
  exceptions: [], examples: [], glossary_term_ids: [], metric_refs: [], business_domain_ids: [],
});
const statusLabel = (rule: Rule) => rule.current.status === 'revoked' ? 'Đã thu hồi' :
  rule.current.status === 'draft' ? 'Bản nháp' : rule.is_discoverable ? 'Đang dùng' : 'Cần cập nhật';
const metricRefKey = (ref: MetricRef) => `${ref.kind}:${ref.target_key}`;

function conditionValue(condition: Condition): string {
  if (condition.value_type === 'null') return '';
  if (condition.value_type === 'array') return Array.isArray(condition.value) ? condition.value.join(', ') : '';
  return String(condition.value ?? '');
}

function parseCondition(condition: Condition, raw: string): Condition {
  if (condition.value_type === 'null') return { ...condition, value: null };
  if (condition.value_type === 'number') {
    const number = Number(raw);
    if (!raw.trim() || !Number.isFinite(number)) throw new Error('Giá trị số không hợp lệ.');
    return { ...condition, value: number };
  }
  if (condition.value_type === 'boolean') return { ...condition, value: raw === 'true' };
  if (condition.value_type === 'array') {
    const values = raw.split(',').map(value => value.trim()).filter(Boolean);
    if (!values.length) throw new Error('Điều kiện tập hợp cần ít nhất một giá trị.');
    return { ...condition, value: values };
  }
  return { ...condition, value: raw };
}

export function RuleTab({ datasetId, access }: { datasetId: number; access: Access }) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [options, setOptions] = useState<RuleOptions | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<RuleInput>(blank(datasetId));
  const [conditionTexts, setConditionTexts] = useState<string[]>(['']);
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = async () => setRules(await managementApi.rules(datasetId));
  useEffect(() => {
    let active = true;
    setSelected(null); setEditing(false); setLoading(true); setError('');
    Promise.all([managementApi.rules(datasetId), managementApi.ruleOptions(datasetId)])
      .then(([rows, refs]) => { if (active) { setRules(rows); setOptions(refs); setDraft(blank(datasetId, refs.columns[0]?.name)); } })
      .catch(reason => { if (active) setError(String(reason.message || reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [datasetId]);

  const current = rules.find(rule => rule.id === selected) ?? null;
  const visible = useMemo(() => rules.filter(rule =>
    `${rule.name} ${rule.current.description || ''}`.toLocaleLowerCase('vi')
      .includes(search.toLocaleLowerCase('vi'))), [rules, search]);
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await action(); await refresh(); setEditing(false); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Không thể lưu quy tắc.'); }
    finally { setBusy(false); }
  };
  const startCreate = () => {
    setSelected(null); setDraft(blank(datasetId, options?.columns[0]?.name)); setConditionTexts(['']);
    setEditing(true); setError('');
  };
  const startEdit = (rule: Rule) => {
    setSelected(rule.id);
    setDraft({ dataset_id: datasetId, name: rule.name, description: rule.current.description,
      conditions: rule.current.conditions, exceptions: rule.current.exceptions, examples: rule.current.examples,
      glossary_term_ids: rule.current.glossary_term_ids, metric_refs: rule.current.metric_refs,
      business_domain_ids: rule.business_domains.map(domain => domain.id) });
    setConditionTexts(rule.current.conditions.map(conditionValue));
    setEditing(true); setError('');
  };
  const updateCondition = (index: number, values: Partial<Condition>) => {
    setDraft({ ...draft, conditions: draft.conditions.map((condition, position) => position === index
      ? { ...condition, ...values } : condition) });
  };
  const toggleTerm = (id: string) => setDraft({ ...draft, glossary_term_ids: draft.glossary_term_ids.includes(id)
    ? draft.glossary_term_ids.filter(item => item !== id) : [...draft.glossary_term_ids, id] });
  const toggleMetric = (ref: MetricRef) => setDraft({ ...draft, metric_refs: draft.metric_refs.some(item =>
    metricRefKey(item) === metricRefKey(ref)) ? draft.metric_refs.filter(item => metricRefKey(item) !== metricRefKey(ref))
    : [...draft.metric_refs, ref] });
  const save = () => act(async () => {
    if (!draft.name.trim()) throw new Error('Cần nhập tên quy tắc.');
    if (!draft.glossary_term_ids.length) throw new Error('Cần chọn ít nhất một thuật ngữ đã duyệt.');
    const conditions = draft.conditions.map((condition, index) => parseCondition(condition, conditionTexts[index] || ''));
    const input = { ...draft, conditions };
    const saved = current ? await managementApi.updateRule(current.id, {
      description: input.description, conditions: input.conditions, exceptions: input.exceptions,
      examples: input.examples, glossary_term_ids: input.glossary_term_ids, metric_refs: input.metric_refs,
      business_domain_ids: input.business_domain_ids, expected_revision: current.current.number,
    }) : await managementApi.createRule(input);
    setSelected(saved.id);
  });

  return <section className="mg-workspace">
    <div className="mg-stats">
      {Object.entries({ 'Tất cả': rules.length,
        'Bản nháp': rules.filter(rule => rule.current.status === 'draft').length,
        'Đang dùng': rules.filter(rule => rule.is_discoverable).length,
        'Cần cập nhật': rules.filter(rule => !!rule.serving && !rule.is_discoverable).length,
      }).map(([label, value]) => <div className="mg-stat" key={label}><strong>{value}</strong><span>{label}</span></div>)}
    </div>
    {error && <div className="mg-error" role="alert">{error}</div>}
    <div className="mg-columns"><div className="mg-list">
      <div className="mg-list-header"><h2><ScaleIcon size={18} /> Quy tắc</h2></div>
      <div className="mg-list-tools"><Input value={search} onChange={event => setSearch(event.target.value)}
        placeholder="Tìm quy tắc" />
        {access.can_edit && <Button onClick={startCreate}><PlusIcon /> Thêm</Button>}</div>
      {loading ? <p className="mg-empty">Đang tải quy tắc…</p> : visible.length === 0
        ? <p className="mg-empty">Chưa có quy tắc phù hợp.</p>
        : visible.map(rule => <button type="button" className={`mg-list-item ${selected === rule.id ? 'is-selected' : ''}`}
          key={rule.id} onClick={() => { setSelected(rule.id); setEditing(false); setError(''); }}>
          <span><strong>{rule.name}</strong><small>{rule.current.description || 'Chưa có mô tả'}</small></span>
          <Badge variant="secondary">{statusLabel(rule)}</Badge></button>)}
    </div>
    <div className="mg-detail">{editing ? <>
      <div className="mg-detail-header"><h2>{current ? 'Sửa quy tắc' : 'Thêm quy tắc'}</h2>
        <Button variant="ghost" onClick={() => setEditing(false)}>Đóng</Button></div>
      <div className="mg-form">
        <label>Tên quy tắc<Input disabled={!!current} value={draft.name}
          onChange={event => setDraft({ ...draft, name: event.target.value })} /></label>
        <label>Mô tả<Textarea rows={3} value={draft.description || ''}
          onChange={event => setDraft({ ...draft, description: event.target.value || null })} /></label>
        <div><div className="mg-section-header"><strong>Điều kiện</strong><Button variant="outline" size="sm"
          onClick={() => { setDraft({ ...draft, conditions: [...draft.conditions, emptyCondition(options?.columns[0]?.name)] });
            setConditionTexts([...conditionTexts, '']); }}>Thêm điều kiện</Button></div>
          {draft.conditions.map((condition, index) => <div className="mg-condition" key={index}>
            <select className="mg-select" value={condition.column_name}
              onChange={event => updateCondition(index, { column_name: event.target.value })}>
              {options?.columns.map(column => <option key={column.name} value={column.name}>{column.name}</option>)}
            </select>
            <select className="mg-select" value={condition.operator} onChange={event => {
              const operator = event.target.value;
              updateCondition(index, operator === 'is_null' || operator === 'is_not_null'
                ? { operator, value_type: 'null', value: null } : { operator });
            }}>{operators.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
            <select className="mg-select" value={condition.value_type} onChange={event => updateCondition(index, {
              value_type: event.target.value as Condition['value_type'],
            })}>
              {['string', 'number', 'boolean', 'null', 'array'].map(value =>
                <option key={value} value={value}>{value}</option>)}
            </select>
            {condition.value_type === 'boolean' ? <select className="mg-select" value={conditionTexts[index] || 'false'}
              onChange={event => setConditionTexts(conditionTexts.map((text, position) =>
                position === index ? event.target.value : text))}>
              <option value="false">false</option><option value="true">true</option></select>
              : condition.value_type !== 'null' && <Input value={conditionTexts[index] || ''} placeholder="Giá trị"
                onChange={event => setConditionTexts(conditionTexts.map((text, position) =>
                  position === index ? event.target.value : text))} />}
            <Button variant="ghost" size="icon" disabled={draft.conditions.length === 1} title="Bỏ điều kiện"
              onClick={() => { setDraft({ ...draft, conditions: draft.conditions.filter((_, position) => position !== index) });
                setConditionTexts(conditionTexts.filter((_, position) => position !== index)); }}><Trash2Icon /></Button>
          </div>)}</div>
        <div><strong>Thuật ngữ đã duyệt</strong><div className="mg-check-list">{options?.glossary_terms.length
          ? options.glossary_terms.map(term => <label key={term.id}><input type="checkbox"
            checked={draft.glossary_term_ids.includes(term.id)} onChange={() => toggleTerm(term.id)} />{term.name}</label>)
          : <p className="mg-muted">Cần duyệt một thuật ngữ liên kết với dataset trước.</p>}</div></div>
        <div><strong>Metric liên quan</strong><div className="mg-check-list">{options?.metrics.filter(metric =>
          metric.origin === 'superset' || metric.status === 'approved').map(metric => {
          const ref: MetricRef = { kind: metric.origin === 'manual' ? 'metric' : 'superset_metric', target_key: metric.id };
          return <label key={metricRefKey(ref)}><input type="checkbox"
            checked={draft.metric_refs.some(item => metricRefKey(item) === metricRefKey(ref))}
            onChange={() => toggleMetric(ref)} />{metric.label || metric.name}</label>;
        })}</div></div>
        <div><div className="mg-section-header"><strong>Ngoại lệ</strong><Button variant="outline" size="sm"
          onClick={() => setDraft({ ...draft, exceptions: [...draft.exceptions, { when: '', outcome: '' }] })}>Thêm</Button></div>
          {draft.exceptions.map((item, index) => <div className="mg-form-grid" key={index}>
            <Input placeholder="Khi nào" value={item.when} onChange={event => setDraft({ ...draft, exceptions:
              draft.exceptions.map((entry, position) => position === index ? { ...entry, when: event.target.value } : entry) })} />
            <Input placeholder="Kết quả" value={item.outcome} onChange={event => setDraft({ ...draft, exceptions:
              draft.exceptions.map((entry, position) => position === index ? { ...entry, outcome: event.target.value } : entry) })} />
            <Button variant="ghost" size="sm" onClick={() => setDraft({ ...draft,
              exceptions: draft.exceptions.filter((_, position) => position !== index) })}>Bỏ</Button></div>)}</div>
        <div><div className="mg-section-header"><strong>Ví dụ</strong><Button variant="outline" size="sm"
          onClick={() => setDraft({ ...draft, examples: [...draft.examples, { question: '', intent: '' }] })}>Thêm</Button></div>
          {draft.examples.map((item, index) => <div className="mg-form-grid" key={index}>
            <Input placeholder="Câu hỏi" value={item.question} onChange={event => setDraft({ ...draft, examples:
              draft.examples.map((entry, position) => position === index ? { ...entry, question: event.target.value } : entry) })} />
            <Input placeholder="Ý định" value={item.intent} onChange={event => setDraft({ ...draft, examples:
              draft.examples.map((entry, position) => position === index ? { ...entry, intent: event.target.value } : entry) })} />
            <Button variant="ghost" size="sm" onClick={() => setDraft({ ...draft,
              examples: draft.examples.filter((_, position) => position !== index) })}>Bỏ</Button></div>)}</div>
        <div className="mg-actions"><Button disabled={busy} onClick={() => void save()}>
          {busy ? 'Đang lưu…' : 'Lưu bản nháp'}</Button></div>
      </div>
    </> : current ? <>
      <div className="mg-detail-header"><div><h2>{current.name}</h2><Badge variant="secondary">{statusLabel(current)}</Badge></div>
        {access.can_edit && <Button variant="outline" onClick={() => startEdit(current)}>Chỉnh sửa</Button>}</div>
      <div className="mg-detail-body"><p>{current.current.description || 'Chưa có mô tả.'}</p>
        <h3>Điều kiện</h3><div className="mg-pills">{current.current.conditions.map((condition, index) =>
          <Badge variant="secondary" key={index}>{condition.column_name} {operators.find(([key]) => key === condition.operator)?.[1]}
            {' '}{conditionValue(condition)}</Badge>)}</div>
        <h3>Liên kết</h3><p className="mg-muted">{current.current.glossary_term_ids.length} thuật ngữ ·
          {' '}{current.current.metric_refs.length} metric</p>
        {current.serving && !current.is_discoverable && <div className="mg-warning">
          Liên kết đã đổi; cần sửa và duyệt lại để dùng quy tắc.</div>}
        <div className="mg-actions">
          {access.can_review && current.current.status === 'draft' && <Button disabled={busy}
            onClick={() => void act(() => managementApi.approveRule(current.id, current.current.number))}>Duyệt</Button>}
          {access.can_review && current.serving && <Button variant="outline" disabled={busy}
            onClick={() => void act(() => managementApi.revokeRule(current.id, current.current.number))}>Thu hồi</Button>}
          {(access.can_edit && !current.serving || access.can_review) && <Button variant="destructive" disabled={busy}
            onClick={() => { if (window.confirm('Xóa quy tắc này?')) void act(async () => {
              await managementApi.deleteRule(current.id); setSelected(null);
            }); }}><Trash2Icon /> Xóa</Button>}
        </div>
      </div>
    </> : <div className="mg-placeholder"><ScaleIcon size={28} /><h2>Chọn một quy tắc</h2>
      <p>Đặt điều kiện theo cột, liên kết tri thức và duyệt trước khi dùng.</p></div>}</div></div>
  </section>;
}
