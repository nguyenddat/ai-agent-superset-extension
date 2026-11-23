import { useMemo, useState } from "react"
import useSWR from "swr"
import { ChevronsUpDownIcon, DatabaseIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Combobox, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from "@/components/ui/combobox"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Skeleton } from "@/components/ui/skeleton"
import { ApiError, errorFrom } from "@/lib/api"
import { navigate, pageHref, useSearchParams } from "@/lib/navigation"
import { cn } from "@/lib/utils"

import { useDictionarySummary } from "../data-dictionary/api"
import type { DictionarySummary } from "../data-dictionary/types"
import type { Section } from "./workspace-layout"

// The standalone app scopes the model and the lineage by connection (its route's connectionId); the extension
// scopes them by Superset database, kept in the query string as ?database=<id>.

export type ScopeDatabase = { database_id: number; database_name: string; dataset_count: number }

export type DatabaseScope = {
  // null while the summary loads, or when the user can read no dataset at all.
  databaseId: number | null
  databaseName: string | null
  databases: ScopeDatabase[]
  isLoading: boolean
  error: ApiError | undefined
}

// The databases the user can read datasets of; a dataset without a database (database_id null) cannot be scoped.
export function scopeDatabases(summary: DictionarySummary): ScopeDatabase[] {
  return summary.databases.flatMap((database) =>
    database.database_id === null
      ? []
      : [
          {
            database_id: database.database_id,
            database_name: database.database_name,
            dataset_count: database.schemas.reduce((sum, schema) => sum + schema.tables.length, 0),
          },
        ],
  )
}

const SUPERSET_DATASETS = "/api/v1/dataset/"
const DATASET_PAGE = 100
const MAX_DATASET_PAGES = 20

// The databases of the datasets Superset itself lets the user read, for a user without the extension's view role
// (the chat only needs the query role): the dictionary summary answers them 403.
export async function fetchSupersetDatabases(): Promise<ScopeDatabase[]> {
  const byId = new Map<number, ScopeDatabase>()
  for (let page = 0; page < MAX_DATASET_PAGES; page++) {
    const q = `(columns:!(id,database.id,database.database_name),page:${page},page_size:${DATASET_PAGE})`
    let response: Response
    try {
      response = await fetch(`${SUPERSET_DATASETS}?q=${encodeURIComponent(q)}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      })
    } catch {
      throw new ApiError(0, "Không kết nối được tới Superset.")
    }
    if (!response.ok) throw await errorFrom(response, "Không tải được danh sách dataset của Superset.")
    const body: { count: number; result: { database?: { id: number; database_name: string } | null }[] } =
      await response.json()
    for (const dataset of body.result) {
      if (!dataset.database) continue
      const current = byId.get(dataset.database.id)
      if (current) current.dataset_count += 1
      else {
        byId.set(dataset.database.id, {
          database_id: dataset.database.id,
          database_name: dataset.database.database_name,
          dataset_count: 1,
        })
      }
    }
    if ((page + 1) * DATASET_PAGE >= body.count || body.result.length === 0) break
  }
  return [...byId.values()].sort((a, b) => a.database_name.localeCompare(b.database_name))
}

// ?database= when it names a readable database, else the database of ?dataset= (a link from the dictionary), else
// the first database. A user without the view role (403 on the summary) gets the databases from Superset's own
// dataset list instead, so the chat works for users who may only ask questions.
export function useDatabaseScope(): DatabaseScope {
  const searchParams = useSearchParams()
  const { data: summary, error: summaryError, isLoading: summaryLoading } = useDictionarySummary()
  const forbidden = summaryError?.status === 403
  const fallback = useSWR<ScopeDatabase[], ApiError>(
    forbidden ? "superset-dataset-databases" : null,
    fetchSupersetDatabases,
    { revalidateOnFocus: false },
  )
  const requested = Number(searchParams.get("database"))
  const datasetId = Number(searchParams.get("dataset"))
  const error = forbidden ? fallback.error : summaryError
  const isLoading = summaryLoading || (!summary && !summaryError) || (forbidden && !fallback.data && !fallback.error)

  const databases = useMemo(
    () => (summary ? scopeDatabases(summary) : (fallback.data ?? [])),
    [summary, fallback.data],
  )
  const current =
    databases.find((database) => database.database_id === requested) ??
    (datasetId
      ? databases.find((database) =>
          summary?.databases
            .find((item) => item.database_id === database.database_id)
            ?.schemas.some((schema) => schema.tables.some((table) => table.dataset_id === datasetId)),
        )
      : undefined) ??
    databases[0]

  return {
    databaseId: current?.database_id ?? null,
    databaseName: current?.database_name ?? null,
    databases,
    isLoading,
    error,
  }
}

// What a section shows when the user can read no dataset, so there is no database to scope it to.
export function NoDatabase({ title, className }: { title: string; className?: string }) {
  return (
    <Empty className={cn("border", className)}>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <DatabaseIcon />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>
          Tạo dataset trong Superset, hoặc nhờ quản trị viên cấp quyền đọc dataset,
          để bắt đầu.
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

const TRIGGER = "-ml-2 h-auto max-w-full min-w-0 px-2 py-1 text-base font-semibold"

// The database a section shows, switched in place; styled like the dictionary's TablePicker trigger. With a single
// database there is nothing to choose, so only its name shows.
export function DatabasePicker({ section, className }: { section: Section; className?: string }) {
  const { databaseId, databaseName, databases, isLoading } = useDatabaseScope()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const selected = databases.find((database) => database.database_id === databaseId) ?? null

  if (isLoading) return <Skeleton className={cn("h-8 w-40", className)} />
  if (!selected) return <span className={cn("text-sm text-muted-foreground", className)}>Chưa có database</span>

  if (databases.length === 1) {
    return (
      <span className={cn("flex min-w-0 items-center gap-2 text-base font-semibold", className)}>
        <DatabaseIcon className="size-4 shrink-0 text-muted-foreground" />
        <span className="truncate">{databaseName}</span>
      </span>
    )
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) setQuery("")
      }}
    >
      <PopoverTrigger
        render={<Button variant="ghost" aria-label="Chọn database" className={cn(TRIGGER, className)} />}
      >
        <DatabaseIcon data-icon="inline-start" className="text-muted-foreground" />
        <span className="truncate">{databaseName}</span>
        <ChevronsUpDownIcon data-icon="inline-end" className="text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 max-w-[calc(100vw-2rem)] gap-0 p-0">
        <Combobox
          inline
          open
          items={databases}
          value={selected}
          inputValue={query}
          onInputValueChange={setQuery}
          onValueChange={(value: ScopeDatabase | null) => {
            if (!value) return
            setOpen(false)
            setQuery("")
            if (value.database_id !== databaseId) {
              navigate(pageHref({ section, database: value.database_id }), { replace: true })
            }
          }}
          itemToStringLabel={(database: ScopeDatabase) => database.database_name}
          isItemEqualToValue={(item: ScopeDatabase, value: ScopeDatabase) => item.database_id === value.database_id}
        >
          <ComboboxInput showTrigger={false} placeholder="Tìm database..." className="m-1 mb-0" autoFocus />
          <ComboboxEmpty className="flex empty:hidden">Không có database phù hợp.</ComboboxEmpty>
          <ComboboxList className="max-h-96">
            {(database: ScopeDatabase) => (
              <ComboboxItem key={database.database_id} value={database}>
                <DatabaseIcon />
                <span className="min-w-0 flex-1 truncate">{database.database_name}</span>
                <Badge variant="secondary" className="tabular-nums">
                  {database.dataset_count} bảng
                </Badge>
              </ComboboxItem>
            )}
          </ComboboxList>
        </Combobox>
      </PopoverContent>
    </Popover>
  )
}
