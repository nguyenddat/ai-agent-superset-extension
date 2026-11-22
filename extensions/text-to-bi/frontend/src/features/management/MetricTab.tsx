import React, { useEffect, useMemo, useState } from 'react';
import { PlusIcon, RefreshCwIcon, SigmaIcon, Trash2Icon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

import { managementApi } from './api';
import type { Access, Metric, MetricInput } from './types';

const blank = (datasetId: number): MetricInput => ({
  dataset_id: datasetId, name: '', expression: '', label: null, description: null,
  format: null, currency: null, metric_type: null, warning_text: null, business_domain_ids: [],
});
const fromMetric = (metric: Metric): MetricInput => ({
  dataset_id: metric.dataset_id, name: metric.name, expression: metric.expression, label: metric.label,
  description: metric.description, format: metric.format, currency: metric.currency,
  metric_type: metric.metric_type, warning_text: metric.warning_text,
  business_domain_ids: metric.business_domains.map(domain => domain.id),
});

const statusLabel = (metric: Metric) => metric.origin === 'superset' ? 'Superset' :
  ({ draft: 'Bản nháp', approved: 'Đã duyệt', revoked: 'Đã thu hồi' }[metric.status]);

export function MetricTab({ datasetId, access }: { datasetId: number; access: Access }) {
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<MetricInput>(blank(datasetId));
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    const rows = await managementApi.metrics(datasetId);
    setMetrics(rows);
  };
  useEffect(() => {
    let active = true;
    setLoading(true);
    setSelected(null);
    setEditing(false);
    setDraft(blank(datasetId));
    managementApi.metrics(datasetId).then(rows => { if (active) setMetrics(rows); })
      .catch(reason => { if (active) setError(String(reason.message || reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [datasetId]);

  const current = metrics.find(metric => metric.id === selected) ?? null;
  const visible = useMemo(() => metrics.filter(metric =>
    `${metric.name} ${metric.label || ''} ${metric.description || ''}`.toLocaleLowerCase('vi')
      .includes(search.toLocaleLowerCase('vi'))), [metrics, search]);
  const counts = {
    all: metrics.length, manual: metrics.filter(metric => metric.origin === 'manual').length,
    superset: metrics.filter(metric => metric.origin === 'superset').length,
    approved: metrics.filter(metric => metric.status === 'approved').length,
  };
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError('');
    try { await action(); await refresh(); setEditing(false); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Không thể lưu metric.'); }
    finally { setBusy(false); }
  };
  const startCreate = () => { setSelected(null); setDraft(blank(datasetId)); setEditing(true); setError(''); };
  const startEdit = (metric: Metric) => { setSelected(metric.id); setDraft(fromMetric(metric)); setEditing(true); setError(''); };
  const save = () => act(async () => {
    if (!draft.name.trim() || !draft.expression.trim()) throw new Error('Cần nhập tên và biểu thức metric.');
    const saved = current?.origin === 'manual'
      ? await managementApi.updateMetric(current.id, draft)
      : await managementApi.createMetric(draft);
    setSelected(saved.id);
  });

  return <section className="mg-workspace">
    <div className="mg-stats">
      {Object.entries({ 'Tất cả': counts.all, 'Tự tạo': counts.manual, 'Superset': counts.superset,
        'Đã duyệt': counts.approved }).map(([label, value]) =>
        <div className="mg-stat" key={label}><strong>{value}</strong><span>{label}</span></div>)}
    </div>
    {error && <div className="mg-error" role="alert">{error}</div>}
    <div className="mg-columns">
      <div className="mg-list">
        <div className="mg-list-header"><h2><SigmaIcon size={18} /> Metric</h2>
          <Button variant="ghost" size="icon" title="Tải lại" onClick={() => void act(refresh)}><RefreshCwIcon /></Button>
        </div>
        <div className="mg-list-tools"><Input value={search} onChange={event => setSearch(event.target.value)}
          placeholder="Tìm metric" />
          {access.can_edit && <Button onClick={startCreate}><PlusIcon /> Thêm</Button>}
        </div>
        {loading ? <p className="mg-empty">Đang tải metric…</p> : visible.length === 0
          ? <p className="mg-empty">Chưa có metric phù hợp.</p>
          : visible.map(metric => <button key={`${metric.origin}-${metric.id}`} type="button"
            className={`mg-list-item ${selected === metric.id ? 'is-selected' : ''}`}
            onClick={() => { setSelected(metric.id); setEditing(false); setError(''); }}>
            <span><strong>{metric.label || metric.name}</strong><small>{metric.name}</small></span>
            <Badge variant="secondary">{statusLabel(metric)}</Badge>
          </button>)}
      </div>
      <div className="mg-detail">
        {editing ? <>
          <div className="mg-detail-header"><h2>{current ? 'Sửa metric' : 'Tạo metric'}</h2>
            <Button variant="ghost" onClick={() => setEditing(false)}>Đóng</Button></div>
          <div className="mg-form">
            <label>Tên metric<Input value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label>
            <label>Nhãn hiển thị<Input value={draft.label || ''} onChange={event => setDraft({ ...draft, label: event.target.value || null })} /></label>
            <label>Biểu thức SQL<Textarea rows={5} value={draft.expression}
              onChange={event => setDraft({ ...draft, expression: event.target.value })} /></label>
            <label>Mô tả<Textarea rows={3} value={draft.description || ''}
              onChange={event => setDraft({ ...draft, description: event.target.value || null })} /></label>
            <div className="mg-form-grid">
              <label>Định dạng<Input value={draft.format || ''} onChange={event => setDraft({ ...draft, format: event.target.value || null })} /></label>
              <label>Đơn vị tiền<Input value={draft.currency || ''} onChange={event => setDraft({ ...draft, currency: event.target.value || null })} /></label>
            </div>
            <label>Cảnh báo<Textarea rows={2} value={draft.warning_text || ''}
              onChange={event => setDraft({ ...draft, warning_text: event.target.value || null })} /></label>
            <div className="mg-actions"><Button disabled={busy} onClick={() => void save()}>{busy ? 'Đang lưu…' : 'Lưu metric'}</Button></div>
          </div>
        </> : current ? <>
          <div className="mg-detail-header"><div><h2>{current.label || current.name}</h2>
            <Badge variant="secondary">{statusLabel(current)}</Badge></div>
            {current.origin === 'manual' && access.can_edit &&
              <Button variant="outline" onClick={() => startEdit(current)}>Chỉnh sửa</Button>}</div>
          <div className="mg-detail-body">
            <p className="mg-muted">{current.description || 'Chưa có mô tả.'}</p>
            <h3>Biểu thức</h3><pre className="mg-code">{current.expression}</pre>
            {current.warning_text && <div className="mg-warning">{current.warning_text}</div>}
            {current.origin === 'manual' && <div className="mg-actions">
              {access.can_review && current.status === 'draft' &&
                <Button disabled={busy} onClick={() => void act(() => managementApi.approveMetric(current.id))}>Duyệt</Button>}
              {access.can_review && current.status === 'approved' &&
                <Button variant="outline" disabled={busy} onClick={() => void act(() => managementApi.revokeMetric(current.id))}>Thu hồi</Button>}
              {(access.can_edit && current.status !== 'approved' || access.can_review) &&
                <Button variant="destructive" disabled={busy} onClick={() => {
                  if (window.confirm('Xóa metric này?')) void act(async () => { await managementApi.deleteMetric(current.id); setSelected(null); });
                }}><Trash2Icon /> Xóa</Button>}
            </div>}
          </div>
        </> : <div className="mg-placeholder"><SigmaIcon size={28} /><h2>Chọn một metric</h2>
          <p>Xem công thức và trạng thái duyệt, hoặc thêm metric mới cho dataset.</p></div>}
      </div>
    </div>
  </section>;
}
