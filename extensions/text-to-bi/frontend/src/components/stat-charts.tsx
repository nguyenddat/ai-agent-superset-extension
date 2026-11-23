import * as React from "react"

import { cn } from "@/lib/utils"

// The standalone app draws these two charts with recharts through shadcn's ui/chart. Here they are plain HTML and
// SVG with the same geometry (28px rows, 16px bars, value labels, a grid under the columns) and shadcn's tooltip
// look: two small charts do not justify recharts and its React 18 store dependencies inside a React 17 remote.

export type BarRow = { name: string; value: number }

const ROW = 28
const OTHER = "Khác"

// The card shadcn's ChartTooltipContent draws, without the colour indicator.
function Tip({ label, unit, value, className }: { label: string; unit: string; value: number; className?: string }) {
  return (
    <div
      role="presentation"
      className={cn(
        "pointer-events-none absolute z-10 grid min-w-32 items-start gap-1.5 rounded-lg border border-border/50",
        "bg-background px-2.5 py-1.5 text-xs whitespace-nowrap shadow-xl",
        className,
      )}
    >
      <div className="font-medium">{label}</div>
      <div className="flex items-center justify-between gap-4 leading-none">
        <span className="text-muted-foreground">{unit}</span>
        <span className="font-mono font-medium text-foreground tabular-nums">{value.toLocaleString("vi-VN")}</span>
      </div>
    </div>
  )
}

const truncate = (value: string) => (value.length > 16 ? `${value.slice(0, 15)}…` : value)

/** One series ranked as horizontal bars, the tail past `limit` folded into "Khác". */
export function GroupBars({ title, unit, rows, limit = 6 }: { title: string; unit: string; rows: BarRow[]; limit?: number }) {
  const [hover, setHover] = React.useState<number | null>(null)
  const sorted = [...rows].sort((a, b) => b.value - a.value || a.name.localeCompare(b.name, "vi"))
  const shown =
    sorted.length > limit
      ? [
          ...sorted.slice(0, limit - 1),
          { name: OTHER, value: sorted.slice(limit - 1).reduce((sum, row) => sum + row.value, 0) },
        ]
      : sorted
  const max = Math.max(...shown.map((row) => row.value), 1)

  return (
    <figure className="flex flex-col gap-2">
      <figcaption className="text-sm font-medium">{title}</figcaption>
      <div
        role="img"
        aria-label={`${title}: ${shown.map((row) => `${row.name} ${row.value}`).join(", ")} ${unit}`}
        className="flex w-full flex-col"
        style={{ height: shown.length * ROW + 8 }}
        onMouseLeave={() => setHover(null)}
      >
        {shown.map((row, index) => (
          <div
            key={row.name}
            className={cn("relative grid grid-cols-[112px_minmax(0,1fr)] items-center", hover === index && "bg-muted")}
            style={{ height: ROW }}
            onMouseEnter={() => setHover(index)}
          >
            <span title={row.name} className="truncate pr-2 text-right text-xs text-muted-foreground">
              {truncate(row.name)}
            </span>
            {/* 36px on the right keeps room for the value after the longest bar, as the chart's right margin did. */}
            <div className="relative flex h-4 items-center pr-9">
              <div
                className="h-full rounded-r bg-chart-1 transition-[width] duration-300"
                style={{ width: `${(row.value / max) * 100}%` }}
              />
              <span className="pl-1.5 text-xs text-foreground tabular-nums">{row.value}</span>
            </div>
            {hover === index ? (
              <Tip label={row.name} unit={unit} value={row.value} className="top-full left-[124px] mt-0.5" />
            ) : null}
          </div>
        ))}
      </div>
    </figure>
  )
}

// Round tick steps (1, 2, 5 × 10^n) so a handful of integer gridlines span the tallest column.
function ticksFor(max: number) {
  if (max <= 0) return [0, 1]
  const rough = max / 4
  const power = 10 ** Math.floor(Math.log10(rough))
  const step = Math.max(1, [1, 2, 5, 10].map((m) => m * power).find((m) => m >= rough) ?? power * 10)
  const top = Math.ceil(max / step) * step
  const ticks: number[] = []
  for (let tick = 0; tick <= top; tick += step) ticks.push(tick)
  return ticks
}

/** One series as columns over a few named categories or days; every column carries its value. */
export function ColumnBars({
  title,
  unit,
  rows,
  height = 150,
  tickFormatter,
}: {
  title: string
  unit: string
  rows: BarRow[]
  height?: number
  tickFormatter?: (value: string) => string
}) {
  const [hover, setHover] = React.useState<number | null>(null)
  const labelled = rows.length <= 16
  const ticks = ticksFor(Math.max(...rows.map((row) => row.value), 0))
  const top = ticks[ticks.length - 1] || 1
  // Like recharts' "preserveStartEnd": the first and last names always show, the ones between thin out.
  const every = Math.max(1, Math.ceil(rows.length / 8))
  const showName = (index: number) => index === 0 || index === rows.length - 1 || index % every === 0
  const format = (name: string) => (tickFormatter ? tickFormatter(name) : name)

  return (
    <figure className="flex flex-col gap-2">
      <figcaption className="text-sm font-medium">{title}</figcaption>
      <div
        role="img"
        aria-label={`${title}: ${rows.map((row) => `${format(row.name)} ${row.value}`).join(", ")} ${unit}`}
        className="grid w-full grid-cols-[2.25rem_minmax(0,1fr)] grid-rows-[minmax(0,1fr)_auto] text-[11px]"
        style={{ height }}
        onMouseLeave={() => setHover(null)}
      >
        {/* 18px on top leaves room for the value above the tallest column. */}
        <div className="relative mt-[18px] text-muted-foreground tabular-nums">
          {ticks.map((tick) => (
            <span
              key={tick}
              className="absolute right-2 translate-y-1/2 leading-none"
              style={{ bottom: `${(tick / top) * 100}%` }}
            >
              {tick}
            </span>
          ))}
        </div>
        <div className="relative mt-[18px]">
          {ticks.map((tick) => (
            <div
              key={tick}
              className="absolute inset-x-0 border-t border-border/50"
              style={{ bottom: `${(tick / top) * 100}%` }}
            />
          ))}
          <div className="absolute inset-0 flex items-end gap-0.5 px-1">
            {rows.map((row, index) => (
              <div
                key={row.name}
                className={cn("relative flex h-full flex-1 items-end justify-center", hover === index && "bg-muted")}
                onMouseEnter={() => setHover(index)}
              >
                <div
                  className="relative w-full max-w-6 rounded-t bg-chart-1 transition-[height] duration-300"
                  style={{ height: `${(row.value / top) * 100}%` }}
                >
                  {labelled && row.value ? (
                    <span
                      className={
                        "absolute bottom-full left-1/2 -translate-x-1/2 pb-0.5 text-xs leading-none text-foreground " +
                        "tabular-nums"
                      }
                    >
                      {row.value}
                    </span>
                  ) : null}
                </div>
                {hover === index ? (
                  <Tip
                    label={format(row.name)}
                    unit={unit}
                    value={row.value}
                    className={cn("bottom-1/2", index < rows.length / 2 ? "left-full ml-1" : "right-full mr-1")}
                  />
                ) : null}
              </div>
            ))}
          </div>
        </div>
        <div />
        <div className="flex gap-0.5 px-1 pt-1.5 text-muted-foreground">
          {rows.map((row, index) => (
            <span key={row.name} className="min-w-0 flex-1 truncate text-center" title={format(row.name)}>
              {showName(index) ? format(row.name) : ""}
            </span>
          ))}
        </div>
      </div>
    </figure>
  )
}
