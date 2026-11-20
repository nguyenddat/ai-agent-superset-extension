import React, { useState } from 'react';
import { X } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import type { ColumnTransformation, ReferenceDataset } from './types';

type TransformationFieldsProps = {
  datasets: ReferenceDataset[];
  /** The column being described, which cannot be its own input. */
  datasetId: number;
  columnName: string;
  value: ColumnTransformation | null;
  disabled?: boolean;
  onChange: (value: ColumnTransformation | null) => void;
};

const MAX_OPTIONS = 60;

/**
 * How a column is computed from columns of other tables, declared by hand like a metric's formula: the input columns
 * are picked from a searchable list grouped by table, and the expression is free text that is shown as written.
 * Removing the last input clears the transformation; the typed expression stays on screen and comes back with the next
 * input picked, so swapping the only input does not lose it.
 */
export function TransformationFields({
  datasets, datasetId, columnName, value, disabled = false, onChange,
}: TransformationFieldsProps) {
  const [query, setQuery] = useState('');
  const [keptExpression, setKeptExpression] = useState<string | null>(null);
  const sources = value?.sources ?? [];
  const expression = value ? value.expression : keptExpression;
  const tableName = (id: number) => datasets.find(dataset => dataset.id === id)?.dataset_name ?? `#${id}`;
  const chosen = new Set(sources.map(source => `${source.dataset_id}.${source.column_name}`));
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  let remaining = MAX_OPTIONS;
  const groups = words.length === 0 ? [] : [...datasets]
    .sort((a, b) => a.dataset_name.localeCompare(b.dataset_name))
    .map(dataset => {
      const columns = dataset.columns.filter(name => {
        const text = `${dataset.dataset_name}.${name}`.toLowerCase();
        const own = dataset.id === datasetId && name === columnName;
        return !own && !chosen.has(`${dataset.id}.${name}`) && words.every(word => text.includes(word));
      }).slice(0, Math.max(remaining, 0));
      remaining -= columns.length;
      return { dataset, columns };
    })
    .filter(group => group.columns.length > 0);

  const update = (next: ColumnTransformation) => onChange(next.sources.length > 0 ? next : null);
  const addSource = (dataset_id: number, column_name: string) => {
    update({ expression, sources: [...sources, { dataset_id, column_name }] });
    setQuery('');
  };
  const removeSource = (index: number) => {
    const remainingSources = sources.filter((_, at) => at !== index);
    if (remainingSources.length === 0) setKeptExpression(expression);
    update({ expression, sources: remainingSources });
  };

  return (
    <div className="sl-transformation">
      <div className="sl-column-detail">
        Biến đổi: cột nguồn
        {sources.length > 0 ? (
          <div className="sl-transformation-sources">
            {sources.map((source, index) => (
              <span key={`${source.dataset_id}.${source.column_name}`} className="sl-transformation-source">
                {tableName(source.dataset_id)}.{source.column_name}
                <button
                  type="button" aria-label={`Bỏ ${source.column_name}`} disabled={disabled}
                  onClick={() => removeSource(index)}
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        ) : null}
        <Input
          aria-label={`Tìm cột nguồn cho ${columnName}`}
          placeholder="Tìm bảng hoặc cột, ví dụ tb_gia_tri gia_tri_so"
          disabled={disabled}
          value={query}
          onChange={event => setQuery(event.target.value)}
        />
        {groups.length > 0 ? (
          <div className="sl-transformation-options" aria-label="Cột nguồn tìm được">
            {groups.map(({ dataset, columns }) => (
              <React.Fragment key={dataset.id}>
                <p>{dataset.dataset_name}</p>
                {columns.map(name => (
                  <button key={name} type="button" onClick={() => addSource(dataset.id, name)}>{name}</button>
                ))}
              </React.Fragment>
            ))}
          </div>
        ) : words.length > 0 ? <span className="sl-transformation-empty">Không có cột phù hợp.</span> : null}
      </div>
      <label className="sl-column-detail sl-transformation-expression">
        Biểu thức biến đổi
        <Textarea
          aria-label={`Biểu thức biến đổi của ${columnName}`}
          className="min-h-16 max-h-40 py-1"
          placeholder={
            sources.length > 0 ? 'Ví dụ: AVG(tb_gia_tri_quan_sat.gia_tri_so) theo ngày' : 'Chọn cột nguồn trước'
          }
          disabled={disabled || sources.length === 0}
          value={expression ?? ''}
          onChange={event => update({ expression: event.target.value || null, sources })}
        />
      </label>
    </div>
  );
}
