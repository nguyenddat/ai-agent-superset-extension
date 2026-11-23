import { useMemo, useState } from "react"
import { CircleXIcon, CloudDownloadIcon, DatabaseIcon, PlusIcon, SigmaIcon, TriangleAlertIcon } from "lucide-react"

import { Badge as StatusBadge } from "@/components/badge"
import { EmptyState } from "@/components/empty-state"
import { SearchInput } from "@/components/search-input"
import { SegmentedControl } from "@/components/segmented-control"
import { StatTile } from "@/components/stat-tile"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import type { Access } from "@/lib/access"
import { navigate, pageHref, useSearchParams } from "@/lib/navigation"
import { cn } from "@/lib/utils"

import { useDictionarySummary } from "../data-dictionary/api"
import { allDatasets, type DatasetOption } from "../data-dictionary/dataset-groups"
import { TablePicker } from "../data-dictionary/table-picker"
import type { DictionarySummary } from "../data-dictionary/types"
import { useMetrics } from "./api"
import { domainNames } from "@/features/business-model/domains"
import { METRIC_STATES, metricTitle } from "./labels"
import { MetricDetail } from "./metric-detail"
import { MetricEditor } from "./metric-editor"
import type { Metric, MetricOrigin } from "./types"

type OriginFilter = "all" | MetricOrigin
type Panel = { metricId: string | null; nonce: number }

function WorkspaceSkeleton() {
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[0, 1, 2, 3].map((key) => (
          <Skeleton key={key} className="h-20 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-96 rounded-xl" />
    </div>
  )
}

// The standalone app lists a connection's metrics grouped by table; here knowledge is scoped by Superset dataset,
// so the page shows one dataset at a time, chosen from `?dataset=` the way the data dictionary does.
export function MetricWorkspace({ access }: { access: Access }) {
  const searchParams = useSearchParams()
  const summary = useDictionarySummary()
  const datasets = useMemo(() => (summary.data ? allDatasets(summary.data) : []), [summary.data])
  const requested = Number(searchParams.get("dataset"))
  const current = datasets.find((dataset) => dataset.dataset_id === requested) ?? datasets[0]
  const metrics = useMetrics(current?.dataset_id ?? null)
  // Kept above the list so a metric created on another dataset stays open after switching to it.
  const [panel, setPanel] = useState<Panel | null>(null)

  if (summary.error) {
    return (
      <Alert variant="destructive">
        <CircleXIcon />
        <AlertDescription>{summary.error.message}</AlertDescription>
      </Alert>
    )
  }

  if (summary.data && !current) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <DatabaseIcon />
          </EmptyMedia>
          <EmptyTitle>Chưa có dataset để định nghĩa metric</EmptyTitle>
          <EmptyDescription>
            Tạo dataset trong Superset, hoặc nhờ quản trị viên cấp quyền đọc dataset, để bắt đầu định nghĩa metric.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  const selectDataset = (datasetId: number) => {
    if (datasetId === current?.dataset_id) return
    setPanel(null)
    navigate(pageHref({ section: "metrics", dataset: datasetId }), { replace: true })
  }

  // One dataset failing to load (e.g. access revoked) must not trap the page: the picker stays to leave it.
  if (summary.data && current && metrics.error) {
    return (
      <section className="overflow-hidden rounded-xl border" aria-label={current.display_name}>
        <DatasetHeader summary={summary.data} dataset={current} onSelect={selectDataset} />
        <div className="p-4">
          <Alert variant="destructive">
            <CircleXIcon />
            <AlertDescription>{metrics.error.message}</AlertDescription>
          </Alert>
        </div>
      </section>
    )
  }

  if (!summary.data || !current || !metrics.data) return <WorkspaceSkeleton />

  return (
    <MetricList
      key={current.dataset_id}
      access={access}
      summary={summary.data}
      datasets={datasets}
      dataset={current}
      metrics={metrics.data}
      panel={panel}
      setPanel={setPanel}
      onSelectDataset={selectDataset}
    />
  )
}

// The table header of the standalone group, where the dataset is also switched.
function DatasetHeader({
  summary,
  dataset,
  onSelect,
  children,
}: {
  summary: DictionarySummary
  dataset: DatasetOption
  onSelect: (datasetId: number) => void
  children?: React.ReactNode
}) {
  return (
    <header className="flex items-center gap-3 border-b bg-muted/40 px-4 py-1.5">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2">
        <TablePicker
          summary={summary}
          datasetId={dataset.dataset_id}
          label={dataset.display_name}
          onSelect={onSelect}
        />
        <span className="truncate font-mono text-xs text-muted-foreground">
          {dataset.schema_name ? `${dataset.schema_name}.` : ""}
          {dataset.table_name}
        </span>
      </div>
      {children}
    </header>
  )
}

function MetricList({
  access,
  summary,
  datasets,
  dataset,
  metrics,
  panel,
  setPanel,
  onSelectDataset,
}: {
  access: Access
  summary: DictionarySummary
  datasets: DatasetOption[]
  dataset: DatasetOption
  metrics: Metric[]
  panel: Panel | null
  setPanel: (panel: Panel | null) => void
  onSelectDataset: (datasetId: number) => void
}) {
  const [query, setQuery] = useState("")
  const [origin, setOrigin] = useState<OriginFilter>("all")

  const counts = {
    all: metrics.length,
    manual: metrics.filter((metric) => metric.origin === "manual").length,
    superset: metrics.filter((metric) => metric.origin === "superset").length,
  }
  const approved = metrics.filter((metric) => metric.origin === "manual" && metric.status === "approved").length

  const shown = useMemo(() => {
    const term = query.trim().toLowerCase()
    return metrics
      .filter((metric) => {
        if (origin !== "all" && metric.origin !== origin) return false
        if (!term) return true
        const domains = domainNames(metric.business_domains)
        return [metric.name, metric.label, metric.expression, metric.description, ...domains]
          .filter(Boolean)
          .some((text) => text!.toLowerCase().includes(term))
      })
      .sort((a, b) => Number(b.is_active) - Number(a.is_active) || metricTitle(a).localeCompare(metricTitle(b)))
  }, [metrics, query, origin])

  const filtered = !!query.trim() || origin !== "all"
  const selected = panel?.metricId ? (metrics.find((metric) => metric.id === panel.metricId) ?? null) : null
  // A metric left open on another dataset (e.g. after the back button) is not on this list: show nothing.
  const open = !!panel && (panel.metricId === null || !!selected)

  const openPanel = (metricId: string | null) => setPanel({ metricId, nonce: Date.now() })
  const clearFilters = () => {
    setQuery("")
    setOrigin("all")
  }
  const create = access.can_edit ? () => openPanel(null) : undefined

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Tổng metric" value={counts.all} />
        <StatTile label="Tự tạo" value={counts.manual} />
        <StatTile label="Từ Superset" value={counts.superset} />
        <StatTile label="Đã duyệt" value={approved} total={counts.manual} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          aria-label="Tìm metric"
          placeholder="Tìm theo tên, biểu thức, miền"
          className="w-full sm:w-72"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onSearch={setQuery}
          shortcut="/"
        />
        <SegmentedControl
          label="Nguồn metric"
          size="sm"
          value={origin}
          onValueChange={(value) => setOrigin(value as OriginFilter)}
          options={[
            { value: "all", label: `Tất cả ${counts.all}` },
            { value: "manual", label: `Tự tạo ${counts.manual}` },
            { value: "superset", label: `Superset ${counts.superset}` },
          ]}
        />
        {create ? (
          <div className="ml-auto flex gap-2">
            <Button onClick={create}>
              <PlusIcon data-icon="inline-start" />
              Thêm metric
            </Button>
          </div>
        ) : null}
      </div>

      <div className={cn("grid items-start gap-3", open && "lg:grid-cols-[minmax(0,1fr)_32rem]")}>
        <section className="min-w-0 overflow-hidden rounded-xl border" aria-label={dataset.display_name}>
          <DatasetHeader summary={summary} dataset={dataset} onSelect={onSelectDataset}>
            <Badge variant="outline" className="tabular-nums">
              {shown.length} metric
            </Badge>
            {create ? (
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button variant="ghost" size="icon-sm" aria-label="Thêm metric cho bảng này" onClick={create} />
                  }
                >
                  <PlusIcon />
                </TooltipTrigger>
                <TooltipContent>Thêm metric cho bảng này</TooltipContent>
              </Tooltip>
            ) : null}
          </DatasetHeader>

          {metrics.length === 0 ? (
            <EmptyState
              scene="chart"
              title="Chưa có metric"
              description={
                create
                  ? "Định nghĩa con số dùng chung như Tổng doanh thu hay Số khách hàng, hoặc thêm metric cho dataset " +
                    "ngay trong Superset."
                  : "Bảng này chưa có metric nào. Bạn chỉ có quyền xem."
              }
              action={
                create ? (
                  <Button onClick={create}>
                    <PlusIcon data-icon="inline-start" />
                    Thêm metric
                  </Button>
                ) : undefined
              }
            />
          ) : shown.length === 0 ? (
            <EmptyState
              scene="search"
              title="Không có metric khớp"
              description={
                query.trim() ? `Không thấy metric nào khớp "${query.trim()}".` : "Không có metric nào khớp bộ lọc."
              }
              secondaryAction={filtered ? { label: "Xóa bộ lọc", onAction: clearFilters } : undefined}
            />
          ) : (
            <ul className="flex flex-col divide-y">
              {shown.map((metric) => (
                <li key={`${metric.origin}:${metric.id}`}>
                  <MetricRow
                    metric={metric}
                    selected={metric.id === panel?.metricId}
                    onOpen={() => openPanel(metric.id)}
                  />
                </li>
              ))}
            </ul>
          )}
        </section>

        {panel && open ? (
          <div
            className={
              // Nothing sticky sits above the extension page, unlike the standalone site header.
              "order-first overflow-hidden rounded-xl border lg:sticky lg:top-3 lg:order-none " +
              "lg:h-[calc(100svh-1.5rem)]"
            }
          >
            {selected && (selected.origin === "superset" || !access.can_edit) ? (
              <MetricDetail
                key={panel.nonce}
                metric={selected}
                dataset={dataset}
                canReview={access.can_review}
                onClose={() => setPanel(null)}
              />
            ) : (
              <MetricEditor
                key={panel.nonce}
                datasets={datasets}
                metrics={metrics}
                metric={selected}
                initialDataset={dataset.dataset_id}
                canReview={access.can_review}
                onClose={() => setPanel(null)}
                onSaved={(saved) => {
                  setPanel({ metricId: saved.id, nonce: panel.nonce })
                  // A new metric may go to another dataset than the one on screen; follow it there.
                  if (saved.dataset_id !== dataset.dataset_id) {
                    navigate(pageHref({ section: "metrics", dataset: saved.dataset_id }), { replace: true })
                  }
                }}
                onDeleted={() => setPanel(null)}
              />
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function MetricRow({ metric, selected, onOpen }: { metric: Metric; selected: boolean; onOpen: () => void }) {
  const fromSuperset = metric.origin === "superset"
  const Icon = fromSuperset ? CloudDownloadIcon : SigmaIcon
  const state = METRIC_STATES[metric.status]

  return (
    <button
      type="button"
      aria-current={selected || undefined}
      onClick={onOpen}
      className={cn(
        "grid w-full cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5 text-left " +
          "outline-none transition-colors hover:bg-muted/50 " +
          "focus-visible:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset " +
          "md:grid-cols-[auto_minmax(0,1fr)_minmax(0,1.3fr)_9.5rem]",
        selected && "bg-muted",
        !metric.is_active && "opacity-60",
      )}
    >
      <span className="flex size-8 items-center justify-center rounded-lg border bg-background text-muted-foreground">
        <Icon className="size-4" />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium">{metricTitle(metric)}</span>
          {metric.warning_text ? (
            <TriangleAlertIcon className="size-3.5 shrink-0 text-muted-foreground" aria-label="Có cảnh báo khi dùng" />
          ) : null}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          <span className="font-mono">{metric.name}</span>
          {metric.business_domains.length ? ` · ${domainNames(metric.business_domains).join(" · ")}` : ""}
        </span>
      </span>
      <code
        className={
          "hidden justify-self-start truncate rounded-md bg-muted/60 px-2 py-1 font-mono text-xs md:block " +
          "md:max-w-full"
        }
        title={metric.expression}
      >
        {metric.expression}
      </code>
      <span className="flex items-center justify-end gap-1.5">
        {!metric.is_active ? <Badge variant="destructive">Đã tắt</Badge> : null}
        {fromSuperset ? (
          <Badge variant="secondary">Superset</Badge>
        ) : (
          <StatusBadge size="sm" tone={state.tone} title={state.hint}>
            {state.label}
          </StatusBadge>
        )}
      </span>
    </button>
  )
}
