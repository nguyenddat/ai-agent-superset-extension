import React, { useEffect, useState } from 'react';
import { CircleAlertIcon, CircleCheckIcon, RotateCcwIcon } from 'lucide-react';
import { cn } from 'cn';

import { Button } from '@/components/ui/button';

export type TaskProgressStatus = 'running' | 'done' | 'error';
export type TaskStat = { label: string; value: React.ReactNode };

type TaskProgressProps = {
  title: string;
  status: TaskProgressStatus;
  // The stages, filled left to right; `phase` is the index of the current one.
  phases: string[];
  phase: number;
  startedAt?: number;
  stats?: TaskStat[];
  // Shown while the task runs, e.g. that results are saved as they arrive.
  message?: string;
  errorText?: string;
  onCancel?: () => void;
  onClose?: () => void;
  onRetry?: () => void;
};

function formatElapsed(milliseconds: number) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`;
}

// A long task on one card: title, counters and a timer on the first row, one bar per phase, the single action
// (Cancel while running, Retry after a failure, Close when done) on the right.
export function TaskProgress({
  title, status, phases, phase, startedAt, stats, message, errorText, onCancel, onClose, onRetry,
}: TaskProgressProps) {
  const running = status === 'running';
  const [now, setNow] = useState(() => Date.now());
  const [endedAt, setEndedAt] = useState<number | null>(null);

  useEffect(() => {
    if (!running) {
      setEndedAt(current => current ?? Date.now());
      return undefined;
    }
    setEndedAt(null);
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  const elapsed = startedAt === undefined ? null : (endedAt ?? now) - startedAt;
  const current = Math.min(Math.max(phase, 0), phases.length - 1);

  return (
    <div className="w-full rounded-xl border bg-background px-4 py-3">
      <div className="flex min-h-8 items-center justify-between gap-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <span className="flex min-w-0 items-center gap-1.5">
            {status === 'done' && (
              <CircleCheckIcon className="size-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
            )}
            {status === 'error' && <CircleAlertIcon className="size-3.5 shrink-0 text-destructive" />}
            <span className="truncate text-[13.5px] font-medium">{title}</span>
          </span>
          {stats?.length ? (
            <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
              {stats.map(stat => (
                <span key={stat.label} className="inline-flex items-baseline gap-1">
                  <span className="font-mono text-foreground tabular-nums">{stat.value}</span>
                  {stat.label}
                </span>
              ))}
            </span>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {elapsed !== null && (
            <span className="font-mono text-[11.5px] text-muted-foreground tabular-nums">
              {status === 'done' && <span className="mr-1 font-sans">Hoàn tất</span>}
              {formatElapsed(elapsed)}
            </span>
          )}
          {running && onCancel && <Button variant="outline" size="sm" onClick={onCancel}>Hủy</Button>}
          {status === 'error' && onRetry && (
            <Button variant="outline" size="sm" onClick={onRetry}>
              <RotateCcwIcon data-icon="inline-start" />
              Thử lại
            </Button>
          )}
          {status === 'done' && onClose && <Button size="sm" onClick={onClose}>Đóng</Button>}
        </div>
      </div>

      <div className="mt-2 flex gap-1" aria-hidden="true">
        {phases.map((label, index) => {
          const complete = status === 'done' || index < current;
          const failed = status === 'error' && index === current;
          const live = running && index === current;
          return (
            <span key={label} className="relative h-1 flex-1 overflow-hidden rounded-full bg-border">
              <span
                className={cn(
                  'absolute inset-0 origin-left rounded-full transition-transform duration-500',
                  failed ? 'bg-destructive' : 'bg-foreground', complete || failed ? 'scale-x-100' : 'scale-x-0'
                )}
              />
              {live && <span className="absolute inset-0 animate-pulse rounded-full bg-foreground/50" />}
            </span>
          );
        })}
      </div>
      <div aria-hidden="true" className="mt-1.5 flex gap-1 text-[11.5px]">
        {phases.map((label, index) => (
          <span
            key={label}
            className={cn(
              'flex-1 truncate',
              status === 'error' && index === current ? 'text-destructive'
                : running && index === current ? 'font-medium text-foreground' : 'text-muted-foreground'
            )}
          >
            {label}
          </span>
        ))}
      </div>

      <p role="status" aria-live="polite" className="sr-only">
        {status === 'done' ? `${title} hoàn tất` : status === 'error' ? `${title} thất bại. ${errorText ?? ''}`
          : phases[current]}
      </p>
      {running && message && <p className="pt-1.5 text-xs text-muted-foreground">{message}</p>}
      {status === 'error' && (
        <p className="pt-1.5 text-[12.5px] text-destructive">{errorText ?? 'Đã xảy ra lỗi giữa chừng.'}</p>
      )}
    </div>
  );
}
