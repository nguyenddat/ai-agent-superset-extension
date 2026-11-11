import { isNumericColumnType } from './metricFormat';
import type { MetricFilterOperator, MetricQueryColumn, MetricQueryDataset, MetricQueryFilter } from './types';

/** A filter row as typed: the value stays text until the payload is built. */
export type FilterDraft = { key: number; column: string; operator: MetricFilterOperator; value: string };

export const OPERATORS: Array<{ value: MetricFilterOperator; label: string }> = [
  { value: '==', label: '=' },
  { value: '!=', label: '≠' },
  { value: '>', label: '>' },
  { value: '>=', label: '≥' },
  { value: '<', label: '<' },
  { value: '<=', label: '≤' },
  { value: 'IN', label: 'thuộc' },
  { value: 'NOT IN', label: 'không thuộc' },
];

/** A column's name for people: its Data Dictionary display name, which the API sends as `verbose_name`. */
export const columnLabel = (column: Pick<MetricQueryColumn, 'column_name' | 'verbose_name'>) => (
  column.verbose_name || column.column_name
);
/** The label of a dataset column known only by its name; the name itself when the dataset does not list it. */
export const datasetColumnLabel = (dataset: MetricQueryDataset | undefined, columnName: string) => {
  const column = dataset?.columns.find(item => item.column_name === columnName);
  return column ? columnLabel(column) : columnName;
};
export const isListOperator = (operator: MetricFilterOperator) => operator === 'IN' || operator === 'NOT IN';

const TEMPORAL_TYPE = /DATE|TIME/i;
const MOMENT_TEXT = /^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$/;

/** Turns the typed filter rows into the execute payload, converting numbers and checking dates. */
export function buildFilters(drafts: FilterDraft[], columns: MetricQueryColumn[]): MetricQueryFilter[] {
  return drafts.map(draft => {
    const column = columns.find(item => item.column_name === draft.column);
    if (!column) throw new Error('Chọn cột cho mọi bộ lọc.');
    const numeric = isNumericColumnType(column.type);
    const temporal = column.is_dttm || TEMPORAL_TYPE.test(column.type ?? '');
    const convert = (text: string) => {
      if (temporal && !MOMENT_TEXT.test(text)) {
        throw new Error(
          `Giá trị lọc của cột ${columnLabel(column)} phải là ngày dạng YYYY-MM-DD hoặc ngày giờ YYYY-MM-DD HH:MM:SS.`,
        );
      }
      if (!numeric) return text;
      const number = Number(text);
      if (!Number.isFinite(number)) throw new Error(`Giá trị lọc của cột ${columnLabel(column)} phải là số.`);
      return number;
    };
    if (isListOperator(draft.operator)) {
      const parts = draft.value.split(',').map(part => part.trim()).filter(Boolean);
      if (parts.length === 0) throw new Error(`Nhập ít nhất một giá trị cho cột ${columnLabel(column)}.`);
      return { column: column.column_name, operator: draft.operator, value: parts.map(convert) };
    }
    if (!draft.value.trim()) throw new Error(`Nhập giá trị lọc cho cột ${columnLabel(column)}.`);
    return { column: column.column_name, operator: draft.operator, value: convert(draft.value.trim()) };
  });
}
