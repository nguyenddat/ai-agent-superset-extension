import React, { useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { AlertCircle, Check, Download, FileSpreadsheet, LoaderCircle, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { requestJson } from './api';
import type { ImportAction, ImportReport, TableFile } from './types';

const MAX_FILE_BYTES = 1_000_000;

const ACTION_LABELS: Record<ImportAction, string> = {
  create: 'Tạo mới',
  update: 'Cập nhật',
  unchanged: 'Giữ nguyên',
  error: 'Lỗi',
};

const ACTION_CLASSES: Record<ImportAction, string> = {
  create: 'is-approved',
  update: 'is-draft',
  unchanged: '',
  error: 'is-revoked',
};

const FIELD_LABELS: Record<string, string> = {
  definition: 'định nghĩa',
  synonyms: 'từ đồng nghĩa',
  steward: 'người phụ trách',
  links: 'liên kết',
  group: 'nhóm',
  name: 'tên',
  conditions: 'điều kiện',
  exceptions: 'ngoại lệ',
  examples: 'ví dụ',
  glossary_terms: 'thuật ngữ',
  metrics: 'metric',
  display_name: 'tên hiển thị',
  description: 'mô tả',
  semantic_role: 'vai trò',
  aggregations: 'phép tổng hợp',
  unit: 'đơn vị',
  business_term: 'thuật ngữ nghiệp vụ',
  contains_pii: 'PII',
};

/** The file's bytes in base64, as the import endpoints read them. */
async function base64Content(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(binary);
}

function saveFile(file: TableFile) {
  const bytes = Uint8Array.from(atob(file.content), character => character.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: file.media_type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = file.filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

type FileTransferProps = {
  /** What one row of the file is, for the dialog title: `thuật ngữ`, `rule`, `data dictionary`. */
  subject: string;
  /** The export endpoint; `/preview` and `/import` below it check and apply an uploaded file. */
  endpoint: string;
  /** How the file is laid out: its columns, how rows match existing items, and what review an import needs. */
  guide: ReactNode;
  disabled?: boolean;
  disabledReason?: string;
  onImported: () => void;
};

/**
 * "Nhập / xuất file": download the current items as a template, upload the edited file, review what each row does,
 * then apply every row in one transaction. Nothing is saved until the administrator confirms a preview without errors.
 */
export function FileTransfer({ subject, endpoint, guide, disabled, disabledReason, onImported }: FileTransferProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [upload, setUpload] = useState<{ filename: string; content: string } | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [applied, setApplied] = useState<ImportReport | null>(null);
  // The browser's own file input is hidden behind a button that matches the dialog's other buttons.
  const fileInput = useRef<HTMLInputElement>(null);

  const reset = () => { setError(''); setUpload(null); setReport(null); setApplied(null); };
  const close = () => { if (!busy) { setOpen(false); reset(); } };

  const download = async (format: 'csv' | 'xlsx') => {
    setBusy(true);
    setError('');
    try {
      saveFile(await requestJson<TableFile>(`${endpoint}?format=${format}`, 'GET'));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Không tải được file.');
    } finally {
      setBusy(false);
    }
  };

  const preview = async (file: File | undefined) => {
    reset();
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      setError('File vượt quá 1 MB.');
      return;
    }
    setBusy(true);
    try {
      const body = { filename: file.name, content: await base64Content(file) };
      setReport(await requestJson<ImportReport>(`${endpoint}/preview`, 'POST', body));
      setUpload(body);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Không đọc được file.');
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!upload) return;
    setBusy(true);
    setError('');
    try {
      setApplied(await requestJson<ImportReport>(`${endpoint}/import`, 'POST', upload));
      setReport(null);
      setUpload(null);
      onImported();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Không nhập được file.');
    } finally {
      setBusy(false);
    }
  };

  const summary = report?.summary;
  const changedRows = report?.rows.filter(row => row.action !== 'unchanged') ?? [];
  const changeCount = summary ? summary.create + summary.update : 0;

  return (
    <>
      <Button
        variant="outline"
        disabled={disabled}
        title={disabled ? disabledReason : undefined}
        onClick={() => setOpen(true)}
      >
        <FileSpreadsheet data-icon="inline-start" /> Nhập / xuất file
      </Button>
      {!open ? null : (
        <Dialog open onOpenChange={next => { if (!next) close(); }}>
          <DialogContent className="sm:max-w-3xl">
            <DialogHeader>
              <DialogTitle>Nhập / xuất file {subject}</DialogTitle>
              <DialogDescription>
                Tải file mẫu đã điền dữ liệu hiện có, sửa hoặc thêm dòng, rồi tải lên để xem trước. Chỉ khi bấm áp
                dụng, mọi dòng mới được lưu cùng lúc; file còn dòng lỗi thì không lưu gì.
              </DialogDescription>
            </DialogHeader>
            <div className="sl-file-transfer-guide">{guide}</div>
            <div className="sl-file-transfer-actions">
              <Button variant="outline" disabled={busy} onClick={() => void download('csv')}>
                <Download data-icon="inline-start" /> Tải file CSV
              </Button>
              <Button variant="outline" disabled={busy} onClick={() => void download('xlsx')}>
                <Download data-icon="inline-start" /> Tải file XLSX
              </Button>
              <Button variant="outline" disabled={busy} onClick={() => fileInput.current?.click()}>
                <Upload data-icon="inline-start" /> Tải lên file đã sửa
              </Button>
              <span className="sl-file-transfer-upload">CSV hoặc XLSX, tối đa 1 MB</span>
              <input
                ref={fileInput}
                type="file"
                hidden
                accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                onChange={event => { void preview(event.target.files?.[0]); event.target.value = ''; }}
              />
            </div>
            {busy ? <p className="sl-metric-muted"><LoaderCircle className="sl-spin" /> Đang xử lý…</p> : null}
            {error ? <div className="sl-metric-error" role="alert"><AlertCircle /> {error}</div> : null}
            {applied ? (
              <p className="sl-save-success" role="status">
                <Check /> Đã lưu: {applied.summary.create} tạo mới, {applied.summary.update} cập nhật,
                {' '}{applied.summary.unchanged} giữ nguyên.
              </p>
            ) : null}
            {report && summary ? (
              <>
                <p className="sl-metric-muted">
                  {upload ? <>File <strong>{upload.filename}</strong>: </> : null}
                  {summary.create} tạo mới · {summary.update} cập nhật · {summary.unchanged} giữ nguyên ·{' '}
                  {summary.error} lỗi
                  {summary.unchanged > 0 ? ' (dòng giữ nguyên không hiện trong bảng)' : ''}
                </p>
                {changedRows.length > 0 ? (
                  <div className="sl-file-transfer-preview">
                    <table className="sl-time-semantics-table">
                      <thead>
                        <tr>
                          <th className="is-row">Dòng</th>
                          <th>Mục</th>
                          <th className="is-action-label">Kết quả</th>
                          <th>Ghi chú</th>
                        </tr>
                      </thead>
                      <tbody>
                        {changedRows.map(row => (
                          <tr key={row.row}>
                            <td>{row.row}</td>
                            <td><code>{row.key || '—'}</code></td>
                            <td>
                              <span className={`sl-metric-state ${ACTION_CLASSES[row.action]}`}>
                                {ACTION_LABELS[row.action]}
                              </span>
                            </td>
                            <td>
                              {row.changes.length > 0
                                ? <div>Đổi: {row.changes.map(field => FIELD_LABELS[field] ?? field).join(', ')}</div>
                                : null}
                              {row.message ? <div>{row.message}</div> : null}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </>
            ) : null}
            <DialogFooter>
              <Button variant="outline" disabled={busy} onClick={close}>Đóng</Button>
              {report ? (
                <Button disabled={busy || summary?.error !== 0 || changeCount === 0} onClick={() => void apply()}>
                  {busy ? <LoaderCircle className="sl-spin" data-icon="inline-start" /> : null}
                  Áp dụng {changeCount} thay đổi
                </Button>
              ) : null}
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}
