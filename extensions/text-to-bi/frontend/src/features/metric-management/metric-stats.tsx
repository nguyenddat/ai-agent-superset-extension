import { useMemo } from "react"
import { ArrowRightIcon, CircleXIcon, SigmaIcon } from "lucide-react"

import { Coverage, RankList } from "@/components/stat-bars"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Link, pageHref } from "@/lib/navigation"

import { useDictionarySummary } from "../data-dictionary/api"
import { allDatasets } from "../data-dictionary/dataset-groups"
import { useAllMetrics } from "./api"

const TOP = 8

// For the overview page: how many datasets have metrics, and which have the most.
export function MetricStatsCard() {
  const { data: summary, error: summaryError } = useDictionarySummary()
  const datasets = useMemo(() => (summary ? allDatasets(summary) : undefined), [summary])
  const ids = useMemo(() => datasets?.map((dataset) => dataset.dataset_id), [datasets])
  const { data: metrics, error: metricsError } = useAllMetrics(ids)
  const error = summaryError ?? metricsError

  const byId = new Map(datasets?.map((dataset) => [dataset.dataset_id, dataset]))
  const perDataset = new Map<number, number>()
  for (const [id, list] of metrics ?? []) {
    const count = list.filter((metric) => metric.is_active).length
    if (count) perDataset.set(id, count)
  }
  const top = [...perDataset].sort(([, a], [, b]) => b - a).slice(0, TOP)

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Bảng đã có metric</CardTitle>
        <CardAction>
          <Button
            variant="ghost"
            size="sm"
            nativeButton={false}
            render={<Link href={pageHref({ section: "metrics" })} />}
          >
            Mở metric
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-5">
        {error ? (
          <Alert variant="destructive">
            <CircleXIcon />
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        ) : !datasets || !metrics ? (
          <Skeleton className="h-56" />
        ) : (
          <>
            <Coverage
              label="Bảng"
              unit="bảng"
              doneLabel="đã có metric"
              done={perDataset.size}
              total={datasets.length}
              large
            />
            <div className="flex flex-1 flex-col gap-2 border-t pt-4">
              <h3 className="text-sm font-medium">Top {TOP} bảng nhiều metric nhất</h3>
              {top.length ? (
                <RankList
                  unit="metric"
                  items={top.map(([id, count]) => {
                    const dataset = byId.get(id)!
                    return {
                      id,
                      label: dataset.display_name,
                      title: `${dataset.schema_name ? `${dataset.schema_name}.` : ""}${dataset.table_name}`,
                      value: count,
                      href: pageHref({ section: "metrics", dataset: id }),
                    }
                  })}
                />
              ) : (
                <Empty className="flex-1 p-4">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <SigmaIcon />
                    </EmptyMedia>
                    <EmptyTitle>Chưa có metric</EmptyTitle>
                    <EmptyDescription>
                      Định nghĩa con số dùng chung như Tổng doanh thu, hoặc thêm metric cho dataset trong Superset.
                    </EmptyDescription>
                  </EmptyHeader>
                  <EmptyContent>
                    <Button
                      size="sm"
                      variant="outline"
                      nativeButton={false}
                      render={<Link href={pageHref({ section: "metrics" })} />}
                    >
                      Thêm metric
                    </Button>
                  </EmptyContent>
                </Empty>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
