import { ArrowRightIcon, CircleXIcon, LinkIcon } from "lucide-react"

import { Coverage, RankList, type RankItem } from "@/components/stat-bars"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Link, navigate, pageHref } from "@/lib/navigation"

import { STATS_LIMIT, useDictionaryStats } from "./api"

type StatsTable = { dataset_id: number; schema_name: string | null; table_name: string; display_name: string }

const rankItem = (table: StatsTable, value: number, hint?: string): RankItem => ({
  id: table.dataset_id,
  label: table.display_name,
  title: [`${table.schema_name ? `${table.schema_name}.` : ""}${table.table_name}`, hint].filter(Boolean).join(" · "),
  value,
})

const openDataset = (datasetId: number) => navigate(pageHref({ section: "dictionary", dataset: datasetId }))

export function DictionaryCoverageCard() {
  const { data: stats, error } = useDictionaryStats()
  const databaseCount = new Set(stats?.schemas.map((schema) => schema.database_name)).size

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Tỷ lệ bảng và cột đã mô tả</CardTitle>
        <CardAction>
          <Button variant="ghost" size="sm" nativeButton={false} render={<Link href={pageHref({ section: "dictionary" })} />}>
            Mở từ điển
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {error ? (
          <Alert variant="destructive">
            <CircleXIcon />
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        ) : !stats ? (
          <Skeleton className="h-40" />
        ) : (
          <>
            <Coverage label="Bảng" unit="bảng" doneLabel="đã mô tả" done={stats.described_table_count} total={stats.table_count} large />
            <Coverage label="Cột" unit="cột" doneLabel="đã mô tả" done={stats.described_column_count} total={stats.column_count} large />
            {stats.schemas.length > 1 && (
              <div className="flex flex-col gap-3 border-t pt-4">
                {stats.schemas.map((schema) => (
                  <Coverage
                    key={`${schema.database_id}:${schema.schema_name}`}
                    label={[databaseCount > 1 ? schema.database_name : null, schema.schema_name ?? "(không có schema)"]
                      .filter(Boolean)
                      .join(" · ")}
                    unit="bảng"
                    doneLabel="đã mô tả"
                    done={schema.described_table_count}
                    total={schema.table_count}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function DictionaryRankCards() {
  const { data: stats, error } = useDictionaryStats()

  if (error || stats?.table_count === 0) return null
  if (!stats) {
    return (
      <div className="grid gap-3 md:grid-cols-2">
        <Skeleton className="h-72 rounded-xl" />
        <Skeleton className="h-72 rounded-xl" />
      </div>
    )
  }

  return (
    <div className="grid gap-3 md:grid-cols-2">
      <Card size="sm">
        <CardHeader>
          <CardTitle>Top {STATS_LIMIT} bảng nhiều cột nhất</CardTitle>
        </CardHeader>
        <CardContent>
          <RankList
            unit="cột"
            onOpen={openDataset}
            items={stats.most_columns.map((table) =>
              rankItem(table, table.column_count, `${table.described_column_count}/${table.column_count} cột đã mô tả`),
            )}
          />
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader>
          <CardTitle>Top {STATS_LIMIT} bảng được tham chiếu nhiều nhất</CardTitle>
        </CardHeader>
        <CardContent className="flex-1">
          {stats.most_referenced.length ? (
            <RankList
              unit="bảng"
              onOpen={openDataset}
              items={stats.most_referenced.map((table) => rankItem(table, table.referencing_table_count))}
            />
          ) : (
            <Empty className="h-full p-4">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <LinkIcon />
                </EmptyMedia>
                <EmptyTitle>Chưa có tham chiếu</EmptyTitle>
                <EmptyDescription>Chưa cột nào trong từ điển khai báo tham chiếu tới bảng khác.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
