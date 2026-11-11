import { format } from 'd3-format';

const integerFormat = format(',d');
const decimalFormat = format(',.2~f');

// A date as Superset's JSON writes it: ISO ("2026-11-17") or HTTP style ("Tue, 17 Nov 2026 00:00:00 GMT").
const DATE_TEXT = /^(?:\d{4}-\d{2}-\d{2}|[A-Z][a-z]{2}, \d{1,2} [A-Z][a-z]{2} \d{4})/;

/**
 * Formats a metric value with the metric's Superset d3 format. Superset-only names such as SMART_NUMBER, or no format,
 * fall back to grouped digits with at most two decimals. A metric whose value is a date, such as the latest day with
 * data, is shown like a date column.
 */
export function formatMetricValue(value: unknown, d3Format: string | null): string {
  if (value === null || value === undefined || value === '') return '—';
  const number = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(number)) {
    return typeof value === 'string' && DATE_TEXT.test(value) ? formatDateValue(value) : String(value);
  }
  if (d3Format) {
    try {
      return format(d3Format)(number);
    } catch {
      // Not a d3 specifier; use the fallback below.
    }
  }
  return Number.isInteger(number) ? integerFormat(number) : decimalFormat(number);
}

/** Shows a time column value as a Vietnamese date, adding the time only when it is not midnight UTC. */
export function formatDateValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const date = new Date(typeof value === 'number' ? value : String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  const isMidnight = date.getUTCHours() === 0 && date.getUTCMinutes() === 0 && date.getUTCSeconds() === 0;
  return isMidnight
    ? date.toLocaleDateString('vi-VN', { timeZone: 'UTC' })
    : date.toLocaleString('vi-VN', { timeZone: 'UTC' });
}

const NUMERIC_TYPE =/INT|FLOAT|DOUBLE|NUMERIC|DECIMAL|REAL|SERIAL|NUMBER/i;

export function isNumericColumnType(columnType: string | null): boolean {
  return NUMERIC_TYPE.test(columnType ?? '');
}
