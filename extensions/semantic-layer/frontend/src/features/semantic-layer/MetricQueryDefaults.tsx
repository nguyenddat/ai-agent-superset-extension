import React, { useState } from 'react';
import { AlertCircle, LoaderCircle, Pencil, Plus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { requestJson, semanticLayerApi } from './api';
import { buildFilters, columnLabel, isListOperator, OPERATORS, type FilterDraft } from './metricFilters';
import type {
  MetricAppliedDefaults, MetricFilterOperator, MetricGrain, MetricQueryDataset, MetricQueryDefaults,
  MetricQueryDefaultsPayload, MetricQueryFilter, MetricReviewItem, MetricTimeAnchor,
} from './types';

export const GRAIN_LABELS: Record<string, string> = {
  instant: 'Thời điểm', hour: 'Giờ', day: 'Ngày', week: 'Tuần', month: 'Tháng', quarter: 'Quý', year: 'Năm',
};
const grainWord = (grain: string) => (GRAIN_LABELS[grain] ?? grain).toLowerCase();
const READ_GRAINS: MetricGrain[] =['hour', 'day', 'week', 'month', 'quarter', 'year'];
const WINDOW_UNITS: MetricGrain[] = READ_GRAINS;
const ANCHOR_LABELS: Record<MetricTimeAnchor, string> = {
  now: 'tính từ thời điểm hiện tại',
  latest_data: 'tính từ mốc dữ liệu mới nhất',
};
const NONE = 'none';

type WindowKind = 'none' | 'last' | 'current' | 'previous' | 'to_date';
type WindowDraft = { kind: WindowKind; count: string; unit: MetricGrain };

const WINDOW_KINDS: Array<{ value: WindowKind; label: string }> = [
  { value: 'none', label: 'Không giới hạn' },
  { value: 'last', label: 'N đơn vị gần nhất' },
  { value: 'current', label: 'Đơn vị hiện tại' },
  { value: 'previous', label: 'Đơn vị liền trước' },
  { value: 'to_date', label: 'Từ đầu đơn vị đến mốc tính' },
];

function parseWindow(value: string | null): WindowDraft {
  const match = value?.match(/^(?:last_(\d+)_(\w+)|(current|previous)_(\w+)|(\w+)_to_date)$/);
  if (!match) return { kind: 'none', count: '7', unit: 'day' };
  if (match[1]) return { kind: 'last', count: match[1], unit: match[2] as MetricGrain };
  if (match[3]) return { kind: match[3] as WindowKind, count: '7', unit: match[4] as MetricGrain };
  return { kind: 'to_date', count: '7', unit: match[5] as MetricGrain };
}

function windowValue(draft: WindowDraft): string | null {
  switch (draft.kind) {
    case 'last': return `last_${draft.count.trim()}_${draft.unit}`;
    case 'current': return `current_${draft.unit}`;
    case 'previous': return `previous_${draft.unit}`;
    case 'to_date': return `${draft.unit}_to_date`;
    default: return null;
  }
}

/** A window in words, such as "7 ngày gần nhất" or "từ đầu tháng". */
export function describeWindow(value: string | null): string | null {
  const draft = parseWindow(value);
  const unit = (GRAIN_LABELS[draft.unit] ?? draft.unit).toLowerCase();
  switch (draft.kind) {
    case 'last': return `${draft.count} ${unit} gần nhất`;
    case 'current': return `${unit} hiện tại`;
    case 'previous': return `${unit} liền trước`;
    case 'to_date': return `từ đầu ${unit} đến mốc tính`;
    default: return null;
  }
}

const OPERATOR_LABELS = new Map(OPERATORS.map(item => [item.value, item.label]));

export function describeFilter(filter: MetricQueryFilter, dataset: MetricQueryDataset | undefined): string {
  const column = dataset?.columns.find(item => item.column_name === filter.column);
  const name = column ? columnLabel(column) : filter.column;
  const value = Array.isArray(filter.value) ? filter.value.join(', ') : String(filter.value);
  return `${name} ${OPERATOR_LABELS.get(filter.operator) ?? filter.operator} ${value}`;
}

/** What a metric run applied from the metric's defaults, in one line. */
export function describeApplied(applied: MetricAppliedDefaults, dataset: MetricQueryDataset | undefined): string {
  const parts = applied.filters
    .filter(item => item.source !== 'time_window')
    .map(item => describeFilter(item, dataset));
  if (applied.time_window) {
    const end = applied.time_window.end_included ? 'đến hết' : 'đến trước';
    parts.push(`thời gian từ ${applied.time_window.start} ${end} ${applied.time_window.end}`);
  }
  if (applied.time_grain) parts.push(`gom theo ${grainWord(applied.time_grain)}`);
  return parts.join(' · ');
}

type Choice = { value: string; label: string };

function ChoiceField(
  { label, items, value, disabled, onChange }:
  { label: string; items: Choice[]; value: string; disabled: boolean; onChange: (value: string) => void },
) {
  return (
    <label>
      {label}
      <Select items={items} value={value} onValueChange={next => onChange(String(next))}>
        <SelectTrigger aria-label={label} className="w-full" disabled={disabled}><SelectValue /></SelectTrigger>
        <SelectContent alignItemWithTrigger={false}>
          <SelectGroup>
            {items.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
          </SelectGroup>
        </SelectContent>
      </Select>
    </label>
  );
}

type EditorProps = {
  metric: MetricReviewItem;
  dataset: MetricQueryDataset | undefined;
  onCancel: () => void;
  onSaved: () => void;
};

function QueryDefaultsEditor({ metric, dataset, onCancel, onSaved }: EditorProps) {
  const current = metric.query_defaults;
  const filterableColumns = dataset?.columns.filter(column => column.filterable) ?? [];
  const [grain, setGrain] = useState<string>(current?.grain ?? NONE);
  const [rowKind, setRowKind] = useState<string>(current?.row_kind_value ?? NONE);
  const [timeColumn, setTimeColumn] = useState<string>(current?.time_column ?? NONE);
  const [timeWindow, setTimeWindow] = useState<WindowDraft>(parseWindow(current?.time_window ?? null));
  const [anchor, setAnchor] = useState<MetricTimeAnchor>(current?.time_anchor ?? 'now');
  const [filterDrafts, setFilterDrafts] = useState<FilterDraft[]>(
    (current?.default_filters ?? []).map((filter, index) => ({
      key: index + 1,
      column: filter.column,
      operator: filter.operator,
      value: Array.isArray(filter.value) ? filter.value.join(', ') : String(filter.value),
    })),
  );
  const [nextFilterKey, setNextFilterKey] = useState(filterDrafts.length + 1);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  const grainItems = [
    { value: NONE, label: 'Không đặt' },
    ...READ_GRAINS.map(value => ({ value, label: GRAIN_LABELS[value] })),
  ];
  const rowKindItems = [
    { value: NONE, label: 'Theo công thức' },
    ...(dataset?.row_kinds ?? [])
      .filter(item => item.value !== null)
      .map(item => ({
        value: item.value as string,
        label: `${item.label || item.value} (${(GRAIN_LABELS[item.grain] ?? item.grain).toLowerCase()})`,
      })),
  ];
  const timeColumnItems = [
    { value: NONE, label: dataset?.time_column ? `Theo từ điển dữ liệu (${dataset.time_column})` : 'Không đặt' },
    ...(dataset?.temporal_columns ?? []).map(name => {
      const column = dataset?.columns.find(item => item.column_name === name);
      return { value: name, label: column ? columnLabel(column) : name };
    }),
  ];
  const unitItems = WINDOW_UNITS
    .filter(unit => timeWindow.kind === 'last' || unit !== 'hour')
    .map(unit => ({ value: unit, label: GRAIN_LABELS[unit] }));
  const anchorItems = (Object.keys(ANCHOR_LABELS) as MetricTimeAnchor[])
    .map(value => ({ value, label: ANCHOR_LABELS[value] }));
  const filterColumnItems = filterableColumns
    .filter(column => column.column_name !== dataset?.row_kind_column && !column.is_dttm)
    .map(column => ({ value: column.column_name, label: columnLabel(column) }));

  const updateFilter = (key: number, change: Partial<FilterDraft>) => {
    setFilterDrafts(drafts => drafts.map(draft => draft.key === key ? { ...draft, ...change } : draft));
  };
  const addFilter = () => {
    setFilterDrafts(drafts => [
      ...drafts, { key: nextFilterKey, column: filterColumnItems[0]?.value ?? '', operator: '==', value: '' },
    ]);
    setNextFilterKey(key => key + 1);
  };

  const save = async () => {
    setSaveError('');
    try {
      if (timeWindow.kind === 'last' && !/^[1-9]\d{0,2}$/.test(timeWindow.count.trim())) {
        throw new Error('Số đơn vị gần nhất phải là số nguyên từ 1 đến 999.');
      }
      const payload: MetricQueryDefaultsPayload = {
        grain: grain === NONE ? null : grain as MetricGrain,
        row_kind_value: rowKind === NONE ? null : rowKind,
        time_column: timeColumn === NONE ? null : timeColumn,
        time_window: windowValue(timeWindow),
        time_anchor: timeWindow.kind === 'none' ? null : anchor,
        default_filters: buildFilters(filterDrafts, filterableColumns),
      };
      setSaving(true);
      await requestJson(semanticLayerApi.metricQueryDefaults(metric.dataset_id, metric.metric_id), 'PUT', payload);
      onSaved();
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : 'Không lưu được.');
      setSaving(false);
    }
  };

  return (
    <div className="sl-metric-definition-editor">
      <div className="sl-metric-defaults-grid">
        {dataset?.row_kind_column ? (
          <ChoiceField label="Loại dòng" items={rowKindItems} value={rowKind} disabled={saving} onChange={setRowKind} />
        ) : null}
        <ChoiceField label="Grain" items={grainItems} value={grain} disabled={saving} onChange={setGrain} />
        <ChoiceField
          label="Cột thời gian" items={timeColumnItems} value={timeColumn} disabled={saving} onChange={setTimeColumn}
        />
        <ChoiceField
          label="Khoảng thời gian"
          items={WINDOW_KINDS}
          value={timeWindow.kind}
          disabled={saving}
          onChange={value => setTimeWindow(draft => ({
            ...draft, kind: value as WindowKind, unit: value !== 'last' && draft.unit === 'hour' ? 'day' : draft.unit,
          }))}
        />
        {timeWindow.kind === 'last' ? (
          <label>
            Số đơn vị
            <Input
              value={timeWindow.count}
              inputMode="numeric"
              disabled={saving}
              onChange={event => setTimeWindow(draft => ({ ...draft, count: event.target.value }))}
            />
          </label>
        ) : null}
        {timeWindow.kind !== 'none' ? (
          <>
            <ChoiceField
              label="Đơn vị"
              items={unitItems}
              value={timeWindow.unit}
              disabled={saving}
              onChange={value => setTimeWindow(draft => ({ ...draft, unit: value as MetricGrain }))}
            />
            <ChoiceField
              label="Mốc tính"
              items={anchorItems}
              value={anchor}
              disabled={saving}
              onChange={value => setAnchor(value as MetricTimeAnchor)}
            />
          </>
        ) : null}
      </div>
      <span className="sl-metric-trial-label">Bộ lọc mặc định</span>
      <div className="sl-metric-trial-field is-stacked">
        {filterDrafts.map(draft => (
          <div key={draft.key} className="sl-metric-filter">
            <Select
              items={filterColumnItems}
              value={draft.column}
              onValueChange={value => updateFilter(draft.key, { column: String(value) })}
            >
              <SelectTrigger size="sm" aria-label="Cột lọc" className="w-full min-w-0"><SelectValue /></SelectTrigger>
              <SelectContent alignItemWithTrigger={false}>
                <SelectGroup>
                  {filterColumnItems.map(item => (
                    <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Select
              items={OPERATORS}
              value={draft.operator}
              onValueChange={value => updateFilter(draft.key, { operator: value as MetricFilterOperator })}
            >
              <SelectTrigger size="sm" aria-label="Phép so sánh" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent alignItemWithTrigger={false}>
                <SelectGroup>
                  {OPERATORS.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
                </SelectGroup>
              </SelectContent>
            </Select>
            <Input
              aria-label="Giá trị lọc"
              className="h-7"
              value={draft.value}
              placeholder={isListOperator(draft.operator) ? 'Giá trị 1, giá trị 2' : 'Giá trị'}
              onChange={event => updateFilter(draft.key, { value: event.target.value })}
            />
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Xoá bộ lọc"
              onClick={() => setFilterDrafts(drafts => drafts.filter(item => item.key !== draft.key))}
            >
              <X />
            </Button>
          </div>
        ))}
        {filterColumnItems.length ? (
          <Button variant="outline" size="sm" className="self-start" disabled={saving} onClick={addFilter}>
            <Plus data-icon="inline-start" /> Thêm bộ lọc mặc định
          </Button>
        ) : null}
      </div>
      <p className="sl-metric-muted">
        Lưu thay đổi làm metric đã duyệt hết hiệu lực cho tới khi được đề xuất và duyệt lại, như khi đổi công thức.
      </p>
      {saveError ? <div className="sl-metric-error" role="alert"><AlertCircle /> {saveError}</div> : null}
      <div className="sl-metrics-actions">
        <Button disabled={saving} onClick={() => void save()}>
          {saving ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : null} Lưu
        </Button>
        <Button variant="outline" disabled={saving} onClick={onCancel}>Huỷ</Button>
      </div>
    </div>
  );
}

type FactsProps = { defaults: MetricQueryDefaults; dataset: MetricQueryDataset | undefined };

function QueryDefaultsFacts({ defaults, dataset }: FactsProps) {
  const rowKind = dataset?.row_kinds.find(item => item.value === defaults.row_kind_value);
  const windowText = describeWindow(defaults.time_window);
  const grain = defaults.grain ? GRAIN_LABELS[defaults.grain] : '—';
  const nativeGrain = defaults.native_grain ? ` (dữ liệu theo ${grainWord(defaults.native_grain)})` : '';
  return (
    <dl className="sl-metrics-facts">
      <div><dt>Grain</dt><dd>{grain}{nativeGrain}</dd></div>
      {defaults.row_kind_value ? (
        <div><dt>Loại dòng</dt><dd>{rowKind?.label || defaults.row_kind_value}</dd></div>
      ) : null}
      <div><dt>Cột thời gian</dt><dd>{defaults.time_column ?? '—'}</dd></div>
      <div>
        <dt>Khoảng thời gian</dt>
        <dd>{windowText ? `${windowText}, ${ANCHOR_LABELS[defaults.time_anchor ?? 'now']}` : 'Không giới hạn'}</dd>
      </div>
      <div>
        <dt>Bộ lọc mặc định</dt>
        <dd>{defaults.default_filters.map(filter => describeFilter(filter, dataset)).join('; ') || '—'}</dd>
      </div>
    </dl>
  );
}

type SectionProps = {
  metric: MetricReviewItem;
  dataset: MetricQueryDataset | undefined;
  readOnly?: boolean;
  onSaved: () => void;
};

/** The metric's grain, time anchor and default filters: how it is read unless a question says otherwise. */
export function MetricQueryDefaultsSection({ metric, dataset, readOnly = false, onSaved }: SectionProps) {
  const [editing, setEditing] = useState(false);
  const defaults = metric.query_defaults;
  return (
    <section className="sl-metrics-section">
      <div className="sl-metrics-section-heading">
        <h4>Grain, mốc thời gian và bộ lọc mặc định</h4>
        {metric.definition && !editing && !readOnly ? (
          <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
            {defaults ? <Pencil data-icon="inline-start" /> : <Plus data-icon="inline-start" />}
            {defaults ? 'Sửa' : 'Đặt'}
          </Button>
        ) : null}
      </div>
      {editing ? (
        <QueryDefaultsEditor
          metric={metric}
          dataset={dataset}
          onCancel={() => setEditing(false)}
          onSaved={() => { setEditing(false); onSaved(); }}
        />
      ) : defaults ? (
        <QueryDefaultsFacts defaults={defaults} dataset={dataset} />
      ) : (
        <p className="sl-metric-muted">
          {metric.definition
            ? 'Chưa đặt. Metric được tính trên mọi dòng và mọi khoảng thời gian, trừ khi câu hỏi nêu điều kiện.'
            : 'Nhập định nghĩa nghiệp vụ trước khi đặt grain, mốc thời gian và bộ lọc mặc định.'}
        </p>
      )}
    </section>
  );
}
