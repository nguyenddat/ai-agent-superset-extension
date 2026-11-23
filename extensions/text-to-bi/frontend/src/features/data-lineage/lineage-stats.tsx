import { ArrowRightIcon, CircleXIcon, WorkflowIcon } from "lucide-react"

import { Coverage, RankList } from "@/components/stat-bars"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Link, pageHref } from "@/lib/navigation"

import { useBusinessModel } from "../business-model/api"
import { useLineageGraph } from "./api"
import { downstreamCounts, lineageEdges } from "./graph"
import { qualifiedName } from "./labels"

const TOP = 8

// The overview card for one Superset database (standalone's card for one connection).
export function LineageStatsCard({ databaseId }: { databaseId: number }) {
  const { data: model, error: modelError } = useBusinessModel(databaseId)
  const { data: graph, error: graphError } = useLineageGraph(databaseId)
  const error = modelError ?? graphError
  const lineageHref = pageHref({ section: "lineage", database: databaseId })

  const tables = new Map(model?.datasets.map((table) => [table.dataset_id, table]))
  const edges = lineageEdges(graph?.edges ?? [])
  const linked = new Set(
    edges.flatMap((edge) => [edge.source_table_id, edge.target_table_id]).filter((id) => tables.has(id)),
  )
  const impact = [...downstreamCounts(edges)]
    .filter(([id]) => tables.has(id))
    .sort(([, a], [, b]) => b.all - a.all || b.direct - a.direct)
    .slice(0, TOP)

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Bảng đã có dòng dữ liệu</CardTitle>
        <CardAction>
          <Button variant="ghost" size="sm" nativeButton={false} render={<Link href={lineageHref} />}>
            Mở dòng dữ liệu
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
        ) : !model || !graph ? (
          <Skeleton className="h-56" />
        ) : (
          <>
            <Coverage
              label="Bảng"
              unit="bảng"
              doneLabel="đã có dòng dữ liệu"
              done={linked.size}
              total={model.datasets.length}
              large
            />
            <div className="flex flex-1 flex-col gap-2 border-t pt-4">
              <h3 className="text-sm font-medium">Top {TOP} bảng ảnh hưởng rộng nhất</h3>
              {impact.length ? (
                <RankList
                  unit="bảng"
                  items={impact.map(([id, count]) => {
                    const table = tables.get(id)!
                    return {
                      id,
                      label: table.display_name,
                      title:
                        `${qualifiedName(table)} · ${count.direct} bảng nhận trực tiếp, ` +
                        `${count.all} bảng tính cả gián tiếp`,
                      value: count.all,
                      href: pageHref({ section: "lineage", database: databaseId, dataset: id }),
                    }
                  })}
                />
              ) : (
                <Empty className="flex-1 p-4">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <WorkflowIcon />
                    </EmptyMedia>
                    <EmptyTitle>Chưa có dòng dữ liệu</EmptyTitle>
                    <EmptyDescription>
                      Khai báo bảng nào tạo ra bảng nào để biết sửa một bảng sẽ ảnh hưởng tới đâu.
                    </EmptyDescription>
                  </EmptyHeader>
                  <EmptyContent>
                    <Button size="sm" variant="outline" nativeButton={false} render={<Link href={lineageHref} />}>
                      Khai báo phép biến đổi
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
