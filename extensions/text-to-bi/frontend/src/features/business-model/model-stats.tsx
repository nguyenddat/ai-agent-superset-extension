import { ArrowRightIcon, CircleXIcon, ShapesIcon } from "lucide-react"

import { Coverage, RankList } from "@/components/stat-bars"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Link, pageHref } from "@/lib/navigation"

import { useBusinessModel } from "./api"
import { domainColor } from "./venn-layout"

// Standalone's card counts one connection's tables; here it counts one Superset database's datasets. The overview
// passes the database it shows (e.g. useDatabaseScope().databaseId); null shows the skeleton until one is known.
export function ModelStatsCard({ databaseId }: { databaseId: number | null }) {
  const { data: model, error } = useBusinessModel(databaseId)
  const href = pageHref({ section: "model", database: databaseId })

  const tableIds = new Set(model?.datasets.map((table) => table.dataset_id))
  // Domains span every database; only this database's datasets are counted.
  const domains = (model?.domains ?? [])
    .map((domain, index) => ({
      domain,
      color: domainColor(domain, index),
      count: domain.dataset_ids.filter((id) => tableIds.has(id)).length,
    }))
    .sort((a, b) => b.count - a.count || a.domain.name.localeCompare(b.domain.name))
  const assigned = new Set(model?.domains.flatMap((domain) => domain.dataset_ids.filter((id) => tableIds.has(id))))

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Bảng đã phân miền nghiệp vụ</CardTitle>
        <CardAction>
          <Button variant="ghost" size="sm" nativeButton={false} render={<Link href={href} />}>
            Mở mô hình
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
        ) : !model ? (
          <Skeleton className="h-56" />
        ) : (
          <>
            <Coverage
              label="Bảng"
              unit="bảng"
              doneLabel="đã phân miền"
              done={assigned.size}
              total={model.datasets.length}
              large
            />
            <div className="flex flex-1 flex-col gap-2 border-t pt-4">
              <h3 className="text-sm font-medium">Số bảng theo miền nghiệp vụ</h3>
              {domains.length ? (
                <RankList
                  unit="bảng"
                  items={domains.map(({ domain, color, count }) => ({
                    id: domain.id,
                    label: domain.name,
                    title: domain.description ?? domain.name,
                    value: count,
                    href,
                    color,
                  }))}
                />
              ) : (
                <Empty className="flex-1 p-4">
                  <EmptyHeader>
                    <EmptyMedia variant="icon">
                      <ShapesIcon />
                    </EmptyMedia>
                    <EmptyTitle>Chưa có miền nghiệp vụ</EmptyTitle>
                    <EmptyDescription>Tạo miền ở tab Mô hình rồi kéo bảng vào để gom theo nghiệp vụ.</EmptyDescription>
                  </EmptyHeader>
                </Empty>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
