import React, { useEffect, useState } from 'react';
import { AlertCircle, ChevronRight, LoaderCircle, Pencil, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { requestJson, semanticLayerApi } from './api';
import { MetricQueryDefaultsSection } from './MetricQueryDefaults';
import type {
  MetricContractEvent, MetricContractEventAction, MetricDefinitionPayload, MetricFormulaReading, MetricQueryDataset,
  MetricReviewItem, MetricUser,
} from './types';

const EVENT_LABELS: Record<MetricContractEventAction, string> = {
  candidate: 'đề xuất công thức',
  approve: 'duyệt',
  revoke: 'thu hồi',
  definition: 'cập nhật định nghĩa',
};

const NO_STEWARD = 'none';
export const formatTime = (value: string | null) => (value ? new Date(value).toLocaleString('vi-VN') : '');

/** The formula in business words: the dictionary's column labels, a ratio as (…) ÷ (…), and the row filter apart. */
function FormulaReading({ name, reading }: { name: string; reading: MetricFormulaReading }) {
  const scale = reading.scale && reading.scale !== '1' ? `${reading.scale} × ` : '';
  return (
    <div className="sl-metrics-reading">
      <p>
        <strong>{name}</strong> ={' '}
        {reading.denominator ? `${scale}(${reading.numerator}) ÷ (${reading.denominator})` : reading.numerator}
      </p>
      {reading.only_rows.length ? (
        <p className="sl-metrics-reading-rows">Chỉ tính các dòng có {reading.only_rows.join(' và ')}</p>
      ) : null}
    </div>
  );
}

type DefinitionEditorProps = {
  metric: MetricReviewItem;
  users: MetricUser[];
  onCancel: () => void;
  onSaved: () => void;
};

function DefinitionEditor({ metric, users, onCancel, onSaved }: DefinitionEditorProps) {
  const [businessDefinition, setBusinessDefinition] = useState(
    metric.definition?.business_definition ?? metric.description ?? '',
  );
  const [unit, setUnit] = useState(metric.definition?.unit ?? '');
  const [stewardId, setStewardId] = useState(String(metric.definition?.steward_id ?? NO_STEWARD));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const stewardItems = [
    { value: NO_STEWARD, label: 'Chưa chỉ định' },
    ...users.map(user => ({ value: String(user.id), label: user.name })),
  ];

  const save = async () => {
    const payload: MetricDefinitionPayload = {
      business_definition: businessDefinition.trim(),
      unit: unit.trim() || null,
      steward_id: stewardId === NO_STEWARD ? null : Number(stewardId),
    };
    setSaving(true);
    setSaveError('');
    try {
      await requestJson(semanticLayerApi.metricDefinition(metric.dataset_id, metric.metric_id), 'PUT', payload);
      onSaved();
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : 'Không lưu được định nghĩa.');
      setSaving(false);
    }
  };

  return (
    <div className="sl-metric-definition-editor">
      <label>
        Định nghĩa nghiệp vụ
        <Textarea
          value={businessDefinition}
          maxLength={4000}
          className="min-h-24"
          placeholder="Metric này đo gì, tính trên tập dữ liệu nào, dùng để trả lời câu hỏi gì."
          disabled={saving}
          onChange={event => setBusinessDefinition(event.target.value)}
        />
      </label>
      <div className="sl-metric-definition-row">
        <label>
          Đơn vị
          <Input
            value={unit}
            maxLength={64}
            placeholder="Ví dụ: °C, mm, %"
            disabled={saving}
            onChange={event => setUnit(event.target.value)}
          />
        </label>
        <label>
          Người phụ trách
          <Select items={stewardItems} value={stewardId} onValueChange={value => setStewardId(String(value))}>
            <SelectTrigger aria-label="Người phụ trách" className="w-full" disabled={saving}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false}>
              <SelectGroup>
                {stewardItems.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
              </SelectGroup>
            </SelectContent>
          </Select>
        </label>
      </div>
      {saveError ? <div className="sl-metric-error" role="alert"><AlertCircle /> {saveError}</div> : null}
      <div className="sl-metrics-actions">
        <Button disabled={saving || !businessDefinition.trim()} onClick={() => void save()}>
          {saving ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : null} Lưu định nghĩa
        </Button>
        <Button variant="outline" disabled={saving} onClick={onCancel}>Huỷ</Button>
      </div>
    </div>
  );
}

function ReviewHistoryEntries({ metric, revision }: { metric: MetricReviewItem; revision: number }) {
  const [events, setEvents] = useState<MetricContractEvent[] | null>(null);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    let active = true;
    setEvents(null);
    setLoadError('');
    requestJson<{ events: MetricContractEvent[] }>(
      semanticLayerApi.metricContractEvents(metric.dataset_id, metric.metric_id), 'GET',
    )
      .then(payload => { if (active) setEvents(payload.events); })
      .catch(reason => {
        if (active) setLoadError(reason instanceof Error ? reason.message : 'Không tải được lịch sử.');
      });
    return () => { active = false; };
  }, [metric.dataset_id, metric.metric_id, revision]);

  if (loadError) return <div className="sl-metric-error" role="alert"><AlertCircle /> {loadError}</div>;
  if (events === null) return <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang tải lịch sử…</p>;
  const contract = metric.contract;
  if (events.length === 0) {
    if (!contract) return <p className="sl-metric-muted">Chưa có hoạt động nào.</p>;
    // Contracts reviewed before the history table existed only keep their latest people.
    const legacyEntries = [
      { label: 'Đề xuất', person: contract.owner_name, time: null },
      { label: 'Duyệt', person: contract.approver_name, time: contract.approved_at },
      { label: 'Thu hồi', person: contract.revoker_name, time: contract.revoked_at },
    ].filter(entry => entry.person);
    return (
      <ol className="sl-metrics-history">
        {legacyEntries.map(entry => (
          <li key={entry.label}>
            <div><strong>{entry.person}</strong> {entry.label.toLowerCase()}</div>
            {entry.time ? <time>{formatTime(entry.time)}</time> : <time>Trước khi có nhật ký</time>}
          </li>
        ))}
      </ol>
    );
  }
  return (
    <ol className="sl-metrics-history">
      {events.map(event => (
        <li key={event.id} className={`is-${event.action}`}>
          <div><strong>{event.actor_name ?? 'Người dùng đã xoá'}</strong> {EVENT_LABELS[event.action]}</div>
          <time>{formatTime(event.created_at)}</time>
          {event.reason ? <blockquote>{event.reason}</blockquote> : null}
          {event.action === 'candidate' && event.expression && event.expression !== metric.expression ? (
            <code title="Công thức lúc đề xuất, khác công thức hiện tại">{event.expression}</code>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function ReviewHistory({ metric, revision }: { metric: MetricReviewItem; revision: number }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="sl-metrics-section">
      <button type="button" className="sl-metrics-disclosure" aria-expanded={open} onClick={() => setOpen(!open)}>
        <ChevronRight /> Lịch sử duyệt
      </button>
      {open ? <ReviewHistoryEntries metric={metric} revision={revision} /> : null}
    </section>
  );
}

type MetricDefinitionPanelProps = {
  metric: MetricReviewItem;
  dataset: MetricQueryDataset | undefined;
  users: MetricUser[];
  historyRevision: number;
  /** Hides the editing controls, for a Semantic Layer Viewer. */
  readOnly?: boolean;
  onDefinitionSaved: () => void;
};

/** The Definition tab: business meaning, how the metric is read and its formula up front, the review history below. */
export function MetricDefinitionPanel(
  { metric, dataset, users, historyRevision, readOnly = false, onDefinitionSaved }: MetricDefinitionPanelProps,
) {
  const [editing, setEditing] = useState(false);
  const definition = metric.definition;

  return (
    <div className="sl-metrics-definition" role="tabpanel">
      {metric.ineligibility ? (
        <div className="sl-metric-warning" role="note">
          <AlertCircle />
          <div><strong>Lý do chưa đủ điều kiện</strong><span>{metric.ineligibility}</span></div>
        </div>
      ) : null}
      <section className="sl-metrics-section">
        <div className="sl-metrics-section-heading">
          <h4>Định nghĩa nghiệp vụ</h4>
          {definition && !editing && !readOnly ? (
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
              <Pencil data-icon="inline-start" /> Sửa
            </Button>
          ) : null}
        </div>
        {editing ? (
          <DefinitionEditor
            metric={metric}
            users={users}
            onCancel={() => setEditing(false)}
            onSaved={() => { setEditing(false); onDefinitionSaved(); }}
          />
        ) : definition ? (
          <>
            <p className="sl-metrics-description">{definition.business_definition}</p>
            <dl className="sl-metrics-facts">
              <div><dt>Đơn vị</dt><dd>{definition.unit ?? '—'}</dd></div>
              <div><dt>Người phụ trách</dt><dd>{definition.steward_name ?? 'Chưa chỉ định'}</dd></div>
            </dl>
          </>
        ) : (
          <div className="sl-metric-empty-definition">
            <span>
              Chưa có định nghĩa nghiệp vụ. Cần nhập trước khi đề xuất để AI Agent hiểu metric này nghĩa là gì.
            </span>
            {readOnly ? null : (
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                <Plus data-icon="inline-start" /> Thêm định nghĩa
              </Button>
            )}
          </div>
        )}
      </section>
      <MetricQueryDefaultsSection metric={metric} dataset={dataset} readOnly={readOnly} onSaved={onDefinitionSaved} />
      <section className="sl-metrics-section">
        <h4>Công thức</h4>
        {metric.reading ? (
          <FormulaReading name={metric.verbose_name || metric.metric_name} reading={metric.reading} />
        ) : null}
        <pre className="sl-metrics-expression">{metric.expression || '—'}</pre>
      </section>
      <ReviewHistory metric={metric} revision={historyRevision} />
    </div>
  );
}
