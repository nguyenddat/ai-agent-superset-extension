import { CircleAlertIcon, ExternalLinkIcon, LockIcon, TriangleAlertIcon, XIcon } from "lucide-react"

import { Badge as StatusBadge } from "@/components/badge"
import { CodeBlock } from "@/components/code-block"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"

import type { DatasetOption } from "../data-dictionary/dataset-groups"
import { DomainBadges } from "@/features/business-model/domains"
import { dateFormat } from "@/lib/format"
import { formatSample, METRIC_STATES, metricTitle } from "./labels"
import { MetricReview } from "./metric-review"
import type { Metric } from "./types"

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-3 py-1.5 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  )
}

const qualified = (dataset: DatasetOption) =>
  `${dataset.schema_name ? `${dataset.schema_name}.` : ""}${dataset.table_name}`

/**
 * A metric read straight from Superset, read-only, with the way back to where it can be edited. A manual metric
 * opens here too when the user may not edit it, with its review state.
 */
export function MetricDetail({
  metric,
  dataset,
  canReview,
  onClose,
}: {
  metric: Metric
  dataset: DatasetOption | undefined
  canReview: boolean
  onClose: () => void
}) {
  const fromSuperset = metric.origin === "superset"
  const sample = formatSample(metric.format, metric.currency)
  // Superset serves this page, so its Explore screen is on the same origin.
  const exploreUrl = `/explore/?datasource_type=table&datasource_id=${metric.dataset_id}`

  return (
    <section aria-label="Chi tiết metric" className="flex size-full min-h-0 flex-col bg-background">
      <header className="flex items-start justify-between gap-3 border-b px-5 py-4">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 className="truncate text-base font-medium">{metricTitle(metric)}</h2>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate font-mono text-xs text-muted-foreground">{metric.name}</span>
            {fromSuperset ? (
              <Badge variant="secondary">Superset</Badge>
            ) : (
              <StatusBadge size="sm" tone={METRIC_STATES[metric.status].tone}>
                {METRIC_STATES[metric.status].label}
              </StatusBadge>
            )}
            {!metric.is_active ? <Badge variant="destructive">Đã tắt</Badge> : null}
          </div>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Đóng" onClick={onClose}>
          <XIcon />
        </Button>
      </header>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-5 px-5 py-5">
          {!fromSuperset ? <MetricReview metric={metric} canReview={canReview} editable={false} /> : null}
          {!metric.is_active ? (
            <Alert variant="destructive">
              <CircleAlertIcon />
              <AlertTitle>Metric đang tắt</AlertTitle>
              <AlertDescription>AI không dùng metric này cho đến khi được bật lại.</AlertDescription>
            </Alert>
          ) : null}
          {metric.warning_text ? (
            <Alert>
              <TriangleAlertIcon />
              <AlertTitle>Cảnh báo khi dùng</AlertTitle>
              <AlertDescription>{metric.warning_text}</AlertDescription>
            </Alert>
          ) : null}
          {metric.description ? <p className="text-sm">{metric.description}</p> : null}

          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">Biểu thức</h3>
            <CodeBlock code={metric.expression} language="sql" collapseAfter={8} className="text-xs" />
          </div>

          <dl className="flex flex-col">
            <Row label="Bảng">
              {dataset ? (
                <>
                  {dataset.display_name}{" "}
                  <span className="font-mono text-xs text-muted-foreground">{qualified(dataset)}</span>
                </>
              ) : (
                <span className="text-muted-foreground">#{metric.dataset_id}</span>
              )}
            </Row>
            {sample ? (
              <Row label="Hiển thị">
                <span className="font-mono tabular-nums">{sample}</span>
                {metric.format ? (
                  <span className="ml-2 font-mono text-xs text-muted-foreground">{metric.format}</span>
                ) : null}
              </Row>
            ) : metric.format ? (
              <Row label="Định dạng">
                <span className="font-mono">{metric.format}</span>
              </Row>
            ) : null}
            {metric.metric_type ? <Row label="Loại metric">{metric.metric_type}</Row> : null}
          </dl>

          {/* The backend classifies only manual metrics into business domains. */}
          {!fromSuperset ? (
            <div className="flex flex-col gap-2">
              <h3 className="text-sm font-medium">Miền nghiệp vụ</h3>
              <DomainBadges domains={metric.business_domains} />
            </div>
          ) : null}

          <Separator />

          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">{fromSuperset ? "Nguồn trên Superset" : "Lịch sử"}</h3>
            <dl className="flex flex-col">
              {fromSuperset ? (
                <>
                  <Row label="Database">{dataset?.database_name ?? "—"}</Row>
                  <Row label="Dataset">
                    {dataset ? (
                      dataset.dataset_kind === "virtual" ? (
                        "Dataset ảo"
                      ) : (
                        <span className="font-mono text-xs">{qualified(dataset)}</span>
                      )
                    ) : (
                      "—"
                    )}
                    <span className="ml-2 text-xs text-muted-foreground">#{metric.dataset_id}</span>
                  </Row>
                </>
              ) : null}
              {metric.created_at ? <Row label="Tạo lúc">{dateFormat.format(new Date(metric.created_at))}</Row> : null}
              {metric.updated_at ? (
                <Row label="Cập nhật lúc">{dateFormat.format(new Date(metric.updated_at))}</Row>
              ) : null}
            </dl>
          </div>
        </div>
      </ScrollArea>

      <footer className="flex flex-wrap items-center gap-2 border-t px-5 py-3">
        <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <LockIcon className="size-3.5" />
          {fromSuperset ? "Chỉ sửa được tại Superset." : "Bạn chỉ có quyền xem metric này."}
        </span>
        {fromSuperset ? (
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            nativeButton={false}
            render={<a href={exploreUrl} target="_blank" rel="noreferrer" />}
          >
            Mở trong Superset
            <ExternalLinkIcon data-icon="inline-end" />
          </Button>
        ) : null}
      </footer>
    </section>
  )
}
