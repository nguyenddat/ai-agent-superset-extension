import React, { useEffect, useMemo, useState } from 'react';
import { BookOpenIcon, PlusIcon, Trash2Icon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

import { managementApi } from './api';
import type { Access, GlossaryLink, RuleOptions, Term, TermInput } from './types';

const blank = (datasetId: number): TermInput => ({
  dataset_id: datasetId, canonical_name: '', definition: '', synonyms: [],
  links: [{ kind: 'table', target_key: String(datasetId) }], business_domain_ids: [],
});
const statusLabel = (term: Term) => term.current.status === 'revoked' ? 'Đã thu hồi' :
  term.current.status === 'draft' ? 'Bản nháp' : 'Đã duyệt';

function linkLabel(link: GlossaryLink, options: RuleOptions | null): string {
  if (link.kind === 'table') return 'Dataset';
  if (link.kind === 'column') return `Cột: ${link.target_key}`;
  const metric = options?.metrics.find(item => item.id === link.target_key &&
    (link.kind === 'metric' ? item.origin === 'manual' : item.origin === 'superset'));
  return `Metric: ${metric?.label || metric?.name || link.target_key}`;
}

export function GlossaryTab({ datasetId, access }: { datasetId: number; access: Access }) {
  const [terms, setTerms] = useState<Term[]>([]);
  const [options, setOptions] = useState<RuleOptions | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<TermInput>(blank(datasetId));
  const [synonymsText, setSynonymsText] = useState('');
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = async () => setTerms(await managementApi.terms(datasetId));
  useEffect(() => {
    let active = true;
    setSelected(null); setEditing(false); setLoading(true); setError(''); setDraft(blank(datasetId));
    Promise.all([managementApi.terms(datasetId), managementApi.ruleOptions(datasetId)])
      .then(([rows, refs]) => { if (active) { setTerms(rows); setOptions(refs); } })
      .catch(reason => { if (active) setError(String(reason.message || reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [datasetId]);

  const current = terms.find(term => term.id === selected) ?? null;
  const visible = useMemo(() => terms.filter(term =>
    `${term.canonical_name} ${term.current.definition}`.toLocaleLowerCase('vi')
      .includes(search.toLocaleLowerCase('vi'))), [terms, search]);
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true); setError('');
    try { await action(); await refresh(); setEditing(false); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Không thể lưu thuật ngữ.'); }
    finally { setBusy(false); }
  };
  const startCreate = () => { setSelected(null); setDraft(blank(datasetId)); setSynonymsText(''); setEditing(true); };
  const startEdit = (term: Term) => {
    setSelected(term.id);
    setDraft({ dataset_id: datasetId, canonical_name: term.canonical_name,
      definition: term.current.definition, synonyms: term.current.synonyms, links: term.current.links,
      business_domain_ids: term.business_domains.map(domain => domain.id) });
    setSynonymsText(term.current.synonyms.join(', '));
    setEditing(true);
  };
  const toggleLink = (link: GlossaryLink) => {
    const exists = draft.links.some(item => item.kind === link.kind && item.target_key === link.target_key);
    setDraft({ ...draft, links: exists ? draft.links.filter(item =>
      item.kind !== link.kind || item.target_key !== link.target_key) : [...draft.links, link] });
  };
  const save = () => act(async () => {
    const input = { ...draft, synonyms: synonymsText.split(/[,\n]/).map(value => value.trim()).filter(Boolean) };
    if (!input.canonical_name.trim() || !input.definition.trim()) throw new Error('Cần nhập tên và định nghĩa.');
    const saved = current ? await managementApi.updateTerm(current.id, {
      definition: input.definition, synonyms: input.synonyms, links: input.links,
      business_domain_ids: input.business_domain_ids, expected_revision: current.current.number,
    }) : await managementApi.createTerm(input);
    setSelected(saved.id);
  });
  const possibleLinks: GlossaryLink[] = [
    { kind: 'table', target_key: String(datasetId) },
    ...(options?.columns.map(column => ({ kind: 'column' as const, target_key: column.name })) || []),
    ...(options?.metrics.filter(metric => metric.origin === 'superset' || metric.status === 'approved')
      .map(metric => ({ kind: metric.origin === 'manual' ? 'metric' as const : 'superset_metric' as const,
        target_key: metric.id })) || []),
  ];

  return <section className="mg-workspace">
    <div className="mg-stats">
      {Object.entries({ 'Tất cả': terms.length,
        'Bản nháp': terms.filter(term => term.current.status === 'draft').length,
        'Đang dùng': terms.filter(term => !!term.serving).length,
        'Đã thu hồi': terms.filter(term => term.current.status === 'revoked').length,
      }).map(([label, value]) => <div className="mg-stat" key={label}><strong>{value}</strong><span>{label}</span></div>)}
    </div>
    {error && <div className="mg-error" role="alert">{error}</div>}
    <div className="mg-columns">
      <div className="mg-list"><div className="mg-list-header"><h2><BookOpenIcon size={18} /> Thuật ngữ</h2></div>
        <div className="mg-list-tools"><Input value={search} onChange={event => setSearch(event.target.value)}
          placeholder="Tìm thuật ngữ" />
          {access.can_edit && <Button onClick={startCreate}><PlusIcon /> Thêm</Button>}</div>
        {loading ? <p className="mg-empty">Đang tải thuật ngữ…</p> : visible.length === 0
          ? <p className="mg-empty">Chưa có thuật ngữ phù hợp.</p>
          : visible.map(term => <button type="button" className={`mg-list-item ${selected === term.id ? 'is-selected' : ''}`}
            key={term.id} onClick={() => { setSelected(term.id); setEditing(false); setError(''); }}>
            <span><strong>{term.canonical_name}</strong><small>{term.current.definition}</small></span>
            <Badge variant="secondary">{statusLabel(term)}</Badge>
          </button>)}
      </div>
      <div className="mg-detail">{editing ? <>
        <div className="mg-detail-header"><h2>{current ? 'Sửa thuật ngữ' : 'Thêm thuật ngữ'}</h2>
          <Button variant="ghost" onClick={() => setEditing(false)}>Đóng</Button></div>
        <div className="mg-form">
          <label>Tên chuẩn<Input disabled={!!current} value={draft.canonical_name}
            onChange={event => setDraft({ ...draft, canonical_name: event.target.value })} /></label>
          <label>Định nghĩa<Textarea rows={5} value={draft.definition}
            onChange={event => setDraft({ ...draft, definition: event.target.value })} /></label>
          <label>Từ đồng nghĩa, cách nhau bằng dấu phẩy<Input value={synonymsText}
            onChange={event => setSynonymsText(event.target.value)} /></label>
          <div><strong>Liên kết tri thức</strong><p className="mg-muted">Chọn dataset, cột hoặc metric liên quan.</p>
            <div className="mg-check-list">{possibleLinks.map(link => <label key={`${link.kind}-${link.target_key}`}>
              <input type="checkbox" checked={draft.links.some(item => item.kind === link.kind && item.target_key === link.target_key)}
                onChange={() => toggleLink(link)} />{linkLabel(link, options)}
            </label>)}</div></div>
          <div className="mg-actions"><Button disabled={busy} onClick={() => void save()}>
            {busy ? 'Đang lưu…' : 'Lưu bản nháp'}</Button></div>
        </div>
      </> : current ? <>
        <div className="mg-detail-header"><div><h2>{current.canonical_name}</h2>
          <Badge variant="secondary">{statusLabel(current)}</Badge></div>
          {access.can_edit && <Button variant="outline" onClick={() => startEdit(current)}>Chỉnh sửa</Button>}</div>
        <div className="mg-detail-body"><p>{current.current.definition}</p>
          <h3>Từ đồng nghĩa</h3><p className="mg-muted">{current.current.synonyms.join(', ') || 'Chưa có'}</p>
          <h3>Liên kết</h3><div className="mg-pills">{current.current.links.length ?
            current.current.links.map(link => <Badge variant="secondary" key={`${link.kind}-${link.target_key}`}>
              {linkLabel(link, options)}</Badge>) : 'Chưa có'}</div>
          {current.serving && current.current.status === 'draft' &&
            <div className="mg-warning">Bản đã duyệt trước đó vẫn đang được dùng cho tới khi bản nháp được duyệt.</div>}
          <div className="mg-actions">
            {access.can_review && current.current.status === 'draft' && <Button disabled={busy}
              onClick={() => void act(() => managementApi.approveTerm(current.id, current.current.number))}>Duyệt</Button>}
            {access.can_review && current.serving && <Button variant="outline" disabled={busy}
              onClick={() => void act(() => managementApi.revokeTerm(current.id, current.current.number))}>Thu hồi</Button>}
            {(access.can_edit && !current.serving || access.can_review) && <Button variant="destructive" disabled={busy}
              onClick={() => { if (window.confirm('Xóa thuật ngữ này?')) void act(async () => {
                await managementApi.deleteTerm(current.id); setSelected(null);
              }); }}><Trash2Icon /> Xóa</Button>}
          </div>
        </div>
      </> : <div className="mg-placeholder"><BookOpenIcon size={28} /><h2>Chọn một thuật ngữ</h2>
        <p>Quản lý định nghĩa, từ đồng nghĩa, liên kết và trạng thái duyệt.</p></div>}</div>
    </div>
  </section>;
}
