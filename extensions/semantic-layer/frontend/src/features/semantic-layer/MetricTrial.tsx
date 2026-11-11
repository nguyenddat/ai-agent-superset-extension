import React, { useState } from 'react';
import { AlertCircle, Check, Copy, LoaderCircle, Play, Plus, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { requestJson, semanticLayerApi } from './api';
import { buildFilters, columnLabel, isListOperator, OPERATORS, type FilterDraft } from './metricFilters';
import { formatDateValue, formatMetricValue, isNumericColumnType } from './metricFormat';
import { describeApplied } from './MetricQueryDefaults';
import type {
  MetricContractExecution, MetricFilterOperator, MetricQueryColumn, MetricQueryDataset, MetricReviewItem,
} from './types';

/** Time, text and key columns describe a row; other numeric columns are measures and rarely make good dimensions. */
const isCategoryColumn = (column: MetricQueryColumn) => (
  column.is_dttm || !isNumericColumnType(column.type) || /_(key|id)$/i.test(column.column_name)
);

type ColumnGroup = { label: string; items: Array<{ value: string; label: string }> };

/** Splits columns into describing columns, listed first, and numeric measures. */
function groupColumns(columns: MetricQueryColumn[]): ColumnGroup[] {
  const toItem = (column: MetricQueryColumn) => ({ value: column.column_name, label: columnLabel(column) });
  return [
    { label: 'Thời gian, phân loại và khoá', items: columns.filter(isCategoryColumn).map(toItem) },
    { label: 'Cột số đo', items: columns.filter(column => !isCategoryColumn(column)).map(toItem) },
  ].filter(group => group.items.length > 0);
}

function ColumnOptions({ groups }: { groups: ColumnGroup[] }) {
  return (
    <SelectContent alignItemWithTrigger={false} className="w-auto min-w-64">
      {groups.map(group => (
        <SelectGroup key={group.label}>
          <SelectLabel>{group.label}</SelectLabel>
          {group.items.map(item => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}
        </SelectGroup>
      ))}
    </SelectContent>
  );
}

type MetricTrialProps = { metric: MetricReviewItem; dataset: MetricQueryDataset | undefined };

/** Runs an approved metric through Superset with chosen dimensions and filters, and shows the formatted result. */
export function MetricTrial({ metric, dataset }: MetricTrialProps) {
  const groupableColumns = dataset?.columns.filter(column => column.groupby) ?? [];
  const filterableColumns = dataset?.columns.filter(column => column.filterable) ?? [];
  const [dimensions, setDimensions] = useState<string[]>([]);
  const [filterDrafts, setFilterDrafts] = useState<FilterDraft[]>([]);
  const [nextFilterKey, setNextFilterKey] = useState(1);
  const [result, setResult] = useState<MetricContractExecution | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState('');
  const [resultView, setResultView] = useState<'table' | 'sql'>('table');
  const [sqlCopied, setSqlCopied] = useState(false);
  const [applyDefaults, setApplyDefaults] = useState(true);

  const addFilter = () => {
    const textColumn = filterableColumns.find(column => !column.is_dttm && !isNumericColumnType(column.type));
    const firstColumn = (textColumn ?? filterableColumns[0])?.column_name ?? '';
    setFilterDrafts(current => [...current, { key: nextFilterKey, column: firstColumn, operator: '==', value: '' }]);
    setNextFilterKey(key => key + 1);
  };
  const updateFilter = (key: number, change: Partial<FilterDraft>) => {
    setFilterDrafts(current => current.map(draft => draft.key === key ? { ...draft, ...change } : draft));
  };
  const removeFilter = (key: number) => setFilterDrafts(current => current.filter(draft => draft.key !== key));

  const run = async () => {
    setRunError('');
    // The previous result belongs to the previous filters, so it must not stay under a new run or its error.
    setResult(null);
    try {
      const filters = buildFilters(filterDrafts, filterableColumns);
      setRunning(true);
      const endpoint = semanticLayerApi.metricContractExecute(metric.dataset_id, metric.metric_id);
      const body = applyDefaults ? { dimensions, filters } : { dimensions, filters, apply_defaults: false };
      setResult(await requestJson<MetricContractExecution>(endpoint, 'POST', body));
    } catch (reason) {
      setRunError(reason instanceof Error ? reason.message : 'Không chạy được metric.');
    } finally {
      setRunning(false);
    }
  };

  const columnByName = new Map(dataset?.columns.map(column => [column.column_name, column]) ?? []);
  const dimensionGroups = groupColumns(groupableColumns);
  const filterColumnGroups = groupColumns(filterableColumns);
  const filterColumnItems = filterColumnGroups.flatMap(group => group.items);
  const headerLabel = (columnName: string) => (columnName === metric.metric_name
    ? metric.verbose_name || metric.metric_name
    : columnLabel(columnByName.get(columnName) ?? { column_name: columnName, verbose_name: null }));
  const cellText = (columnName: string, value: unknown) => {
    if (columnName === metric.metric_name) return formatMetricValue(value, metric.d3format);
    return columnByName.get(columnName)?.is_dttm ? formatDateValue(value) : String(value ?? '—');
  };
  const copySql = async () => {
    if (!result?.sql) return;
    await navigator.clipboard.writeText(result.sql);
    setSqlCopied(true);
    window.setTimeout(() => setSqlCopied(false), 1500);
  };
  const showSql = resultView === 'sql' && Boolean(result?.sql);

  const runIcon = running
    ? <LoaderCircle className="sl-spin" data-icon="inline-start" />
    : <Play data-icon="inline-start" />;

  return (
    <div className="sl-metric-trial" role="tabpanel">
      {metric.state === 'candidate' ? (
        <div className="sl-metric-warning" role="note">
          <AlertCircle />
          {metric.contract?.origin === 'ai_agent' ? (
            <div>
              <strong>Số liệu tạm tính</strong>
              <span>
                Metric do AI Agent dựng, chưa được duyệt; AI Agent dùng nó để trả lời tạm tính cho tới khi được duyệt
                hoặc thu hồi.
              </span>
            </div>
          ) : (
            <div>
              <strong>Bản xem trước</strong>
              <span>
                Metric chưa được duyệt; chỉ quản trị viên chạy được, AI Agent và người dùng khác chưa dùng được.
              </span>
            </div>
          )}
        </div>
      ) : null}
      <div className="sl-metric-trial-config">
        <span className="sl-metric-trial-label">Chiều phân tích</span>
        <div className="sl-metric-trial-field">
          {dimensions.map(columnName => (
            <span key={columnName} className="sl-metric-token">
              {headerLabel(columnName)}
              <button
                type="button"
                aria-label={`Bỏ chiều ${headerLabel(columnName)}`}
                onClick={() => setDimensions(current => current.filter(name => name !== columnName))}
              >
                <X />
              </button>
            </span>
          ))}
          {groupableColumns.length === 0 ? <span className="sl-metric-muted">Không có cột để group by.</span> : (
            <Select
              multiple
              items={dimensionGroups.flatMap(group => group.items)}
              value={dimensions}
              onValueChange={value => setDimensions(value as string[])}
            >
              <SelectTrigger size="sm" aria-label="Chọn chiều phân tích">
                <Plus /> {dimensions.length === 0 ? 'Thêm chiều (để trống = tổng chung)' : 'Thêm chiều'}
              </SelectTrigger>
              <ColumnOptions groups={dimensionGroups} />
            </Select>
          )}
        </div>
        <span className="sl-metric-trial-label">Bộ lọc</span>
        <div className="sl-metric-trial-field is-stacked">
          {filterDrafts.map(draft => (
            <div key={draft.key} className="sl-metric-filter">
              <Select
                items={filterColumnItems}
                value={draft.column}
                onValueChange={value => updateFilter(draft.key, { column: String(value) })}
              >
                <SelectTrigger size="sm" aria-label="Cột lọc" className="w-full min-w-0"><SelectValue /></SelectTrigger>
                <ColumnOptions groups={filterColumnGroups} />
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
              <Button variant="ghost" size="icon-sm" aria-label="Xoá bộ lọc" onClick={() => removeFilter(draft.key)}>
                <X />
              </Button>
            </div>
          ))}
          {filterableColumns.length === 0 ? <span className="sl-metric-muted">Dataset không có cột để lọc.</span> : (
            <Button variant="outline" size="sm" className="self-start" onClick={addFilter}>
              <Plus data-icon="inline-start" /> Thêm bộ lọc
            </Button>
          )}
        </div>
        {metric.query_defaults ? (
          <>
            <span className="sl-metric-trial-label">Mặc định</span>
            <label className="sl-metric-trial-field sl-metric-defaults-toggle">
              <Checkbox checked={applyDefaults} onCheckedChange={checked => setApplyDefaults(checked === true)} />
              Áp dụng grain, khoảng thời gian và bộ lọc mặc định của metric (bộ lọc trên cùng cột sẽ thay mặc định)
            </label>
          </>
        ) : null}
        <div className="sl-metric-trial-run">
          <Button disabled={running} onClick={() => void run()}>
            {runIcon}
            Chạy thử
          </Button>
          {result ? (
            <span className="sl-metric-muted" aria-live="polite">
              {result.row_count} dòng{result.truncated ? ' (đã cắt bớt theo giới hạn số dòng)' : ''}
            </span>
          ) : null}
          {result?.sql ? (
            <div className="sl-metric-view-switch" role="group" aria-label="Kiểu xem kết quả">
              <button type="button" aria-pressed={!showSql} onClick={() => setResultView('table')}>Kết quả</button>
              <button type="button" aria-pressed={showSql} onClick={() => setResultView('sql')}>SQL</button>
            </div>
          ) : null}
          {showSql ? (
            <Button variant="ghost" size="sm" onClick={() => void copySql()}>
              {sqlCopied ? <Check data-icon="inline-start" /> : <Copy data-icon="inline-start" />}
              {sqlCopied ? 'Đã sao chép' : 'Sao chép SQL'}
            </Button>
          ) : null}
        </div>
      </div>
      {runError ? <div className="sl-metric-error" role="alert"><AlertCircle /> {runError}</div> : null}
      {result?.applied_defaults && describeApplied(result.applied_defaults, dataset) ? (
        <p className="sl-metric-muted">Đã áp dụng mặc định: {describeApplied(result.applied_defaults, dataset)}</p>
      ) : null}
      <div className="sl-metric-result">
        {!result ? (
          <p className="sl-metric-result-empty">Chọn chiều phân tích, bộ lọc rồi bấm Chạy thử để xem kết quả.</p>
        ) : showSql ? (
          <pre className="sl-metric-sql" aria-label="SQL Superset đã chạy">{result.sql}</pre>
        ) : result.rows.length === 0 ? (
          <p className="sl-metric-result-empty">Không có dòng nào khớp chiều phân tích và bộ lọc đã chọn.</p>
        ) : (
          <table>
            <thead>
              <tr>
                {result.columns.map(columnName => <th key={columnName} scope="col">{headerLabel(columnName)}</th>)}
              </tr>
            </thead>
            <tbody>
              {result.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {result.columns.map(columnName => (
                    <td key={columnName} className={columnName === metric.metric_name ? 'is-metric' : undefined}>
                      {cellText(columnName, row[columnName])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
