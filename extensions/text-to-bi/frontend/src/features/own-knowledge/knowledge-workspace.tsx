import { useMemo, useState } from "react"
import { CircleXIcon, CopyIcon, LockKeyholeIcon, Table2Icon, TriangleAlertIcon } from "lucide-react"

import { Badge as StatusBadge } from "@/components/badge"
import { EmptyState } from "@/components/empty-state"
import { SearchInput } from "@/components/search-input"
import { SegmentedControl } from "@/components/segmented-control"
import { StatTile } from "@/components/stat-tile"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import type { Access } from "@/lib/access"
import { useSearchParams } from "@/lib/navigation"
import { cn } from "@/lib/utils"

import { useBusinessModel } from "../business-model/api"
import type { ModelTable } from "../business-model/types"
import { useDictionarySummary } from "../data-dictionary/api"
import { allDatasets, type DatasetOption } from "../data-dictionary/dataset-groups"
import { useRulesOfDatasets } from "../expert-rule-management/api"
import type { ExpertRule } from "../expert-rule-management/types"
import { useAllGlossaries } from "../glossary-management/api"
import type { GlossaryTerm } from "../glossary-management/types"
import { useAllMetrics } from "../metric-management/api"
import type { Metric } from "../metric-management/types"
import { DatabasePicker, NoDatabase, useDatabaseScope } from "../workspace/database-scope"
import { SYSTEM_STATES, analyze, systemCatalog, type EntryGroup, type Findings } from "./analysis"
import { useOwnEntries } from "./api"
import { EntryDetail, type PromoteRequest } from "./entry-detail"
import { KIND_ORDER, KINDS, REVIEW_STATES } from "./labels"
import { PromotePanel } from "./promote-panel"
import { useUserNames, type UserName } from "./reviewer"
import type { KnowledgeKind, OwnEntry, ReviewStatus } from "./types"

type StatusFilter = ReviewStatus | "all"
type Panel = { entryId: string; promote: PromoteRequest | null; nonce: number }

const KIND_ITEMS = [
  { value: "all", label: "Mọi loại" },
  ...KIND_ORDER.map((value) => ({ value, label: KINDS[value].label })),
]

// Standalone shows the connection in its page header; the extension picks the database in the section itself.
function PickerRow() {
  return (
    <div className="flex min-h-8 items-center">
      <DatabasePicker section="own-knowledge" />
    </div>
  )
}

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

// The entries of the database's datasets and the catalog those datasets hold, which the analysis compares with.
// Standalone reads one connection's whole catalog; the extension's catalog lives per dataset, so only the datasets
// that have entries are asked, each request shared with the overview cards of the same module.
export function useDatabaseKnowledge(databaseId: number | null, enabled: boolean) {
  const model = useBusinessModel(databaseId)
  const entries = useOwnEntries(enabled)
  const tableIds = useMemo(
    () => (model.data ? new Set(model.data.datasets.map((table) => table.dataset_id)) : null),
    [model.data],
  )
  const scoped = useMemo(
    () => (entries.data && tableIds ? entries.data.filter((entry) => tableIds.has(entry.dataset_id)) : undefined),
    [entries.data, tableIds],
  )
  const datasetIds = useMemo(
    () => (scoped ? [...new Set(scoped.map((entry) => entry.dataset_id))].sort((a, b) => a - b) : null),
    [scoped],
  )
  const glossaries = useAllGlossaries(datasetIds)
  const metrics = useAllMetrics(datasetIds ?? undefined)
  const rules = useRulesOfDatasets(datasetIds)

  // The glossary list keeps the previous datasets' terms while new ones load (keepPreviousData), which would show
  // "no overlap" for a moment after a switch of database; wait for the current key instead.
  const glossaryData = glossaries.isLoading ? undefined : glossaries.data
  const terms = useMemo(
    () => glossaryData?.flatMap((item: { terms: GlossaryTerm[] }) => item.terms) as GlossaryTerm[] | undefined,
    [glossaryData],
  )
  const metricList = useMemo(() => (metrics.data ? [...metrics.data.values()].flat() : undefined), [metrics.data])
  const ruleList = useMemo(() => (rules.data ? [...rules.data.values()].flat() : undefined), [rules.data])

  const error = model.error ?? entries.error ?? glossaries.error ?? metrics.error ?? rules.error
  return {
    model: model.data,
    entries: scoped,
    terms,
    metrics: metricList,
    rules: ruleList,
    error: error as { message: string; status?: number } | undefined,
    // A user who is not an admin gets 403 here; the overview card shows that as a lock rather than an error.
    forbidden: entries.error?.status === 403,
    reload: () => void entries.mutate(),
  }
}

export function KnowledgeWorkspace({ access }: { access: Access }) {
  const { databaseId, isLoading: scopeLoading, error: scopeError } = useDatabaseScope()
  const knowledge = useDatabaseKnowledge(databaseId, access.is_admin)
  const summary = useDictionarySummary()
  const userName = useUserNames(access.is_admin)

  // The section is admin-only (its /admin routes are require_admin); this guards a link opened by someone else.
  if (!access.is_admin) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <LockKeyholeIcon />
          </EmptyMedia>
          <EmptyTitle>Cần quyền quản trị viên</EmptyTitle>
          <EmptyDescription>Chỉ quản trị viên được xem và duyệt tri thức riêng của người dùng.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  const error = scopeError ?? knowledge.error ?? summary.error
  if (error) {
    return (
      <div className="flex flex-col gap-3">
        {scopeError ? null : <PickerRow />}
        <Alert variant="destructive">
          <CircleXIcon />
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      </div>
    )
  }

  if (!scopeLoading && databaseId === null) return <NoDatabase title="Chưa có bảng để duyệt tri thức riêng" />

  const { model, entries, terms, metrics, rules } = knowledge
  if (!model || model.database_id !== databaseId || !entries || !terms || !metrics || !rules || !summary.data) {
    return (
      <div className="flex flex-col gap-3">
        <PickerRow />
        <WorkspaceSkeleton />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <PickerRow />
      {/* Keyed so a switch of database starts with closed panels and fresh filters. */}
      <KnowledgeList
        key={model.database_id}
        entries={entries}
        terms={terms}
        metrics={metrics}
        rules={rules}
        tables={model.datasets}
        datasets={allDatasets(summary.data)}
        userName={userName}
        onReload={knowledge.reload}
      />
    </div>
  )
}

function KnowledgeList({
  entries,
  terms,
  metrics,
  rules,
  tables,
  datasets,
  userName,
  onReload,
}: {
  entries: OwnEntry[]
  terms: GlossaryTerm[]
  metrics: Metric[]
  rules: ExpertRule[]
  tables: ModelTable[]
  datasets: DatasetOption[]
  userName: UserName
  onReload: () => void
}) {
  const params = useSearchParams()
  // `?entry=<id>` opens one entry, so a notification or another screen can link straight to it.
  const requested = params.get("entry")
  const [query, setQuery] = useState("")
  const [status, setStatus] = useState<StatusFilter>(requested ? "all" : "pending")
  const [kind, setKind] = useState<KnowledgeKind | "all">("all")
  // Entries belong to datasets in the extension; with several, the reviewer can keep to one table.
  const [tableId, setTableId] = useState<string>("all")
  const [attentionOnly, setAttentionOnly] = useState(false)
  const [panel, setPanel] = useState<Panel | null>(requested ? { entryId: requested, promote: null, nonce: 0 } : null)

  const tableById = useMemo(() => new Map(tables.map((table) => [table.dataset_id, table])), [tables])
  const datasetById = useMemo(() => new Map(datasets.map((dataset) => [dataset.dataset_id, dataset])), [datasets])
  const { findings, groups } = useMemo(
    () => analyze(entries, systemCatalog(terms, metrics, rules)),
    [entries, terms, metrics, rules],
  )
  const selected = panel ? (entries.find((entry) => entry.id === panel.entryId) ?? null) : null

  const tableName = (datasetId: number) => {
    const table = tableById.get(datasetId)
    return table ? table.display_name || table.table_name : `Dataset #${datasetId}`
  }
  const entryTables = [...new Set(entries.map((entry) => entry.dataset_id))].sort((a, b) =>
    tableName(a).localeCompare(tableName(b), "vi"),
  )
  const tableItems = [
    { value: "all", label: "Mọi bảng" },
    ...entryTables.map((id) => ({ value: String(id), label: tableName(id) })),
  ]

  const pending = entries.filter((entry) => entry.review_status === "pending")
  const counts: Record<StatusFilter, number> = {
    all: entries.length,
    pending: pending.length,
    kept_own: entries.filter((entry) => entry.review_status === "kept_own").length,
    promoted: entries.filter((entry) => entry.review_status === "promoted").length,
  }
  const visible = useMemo(() => {
    const text = query.trim().toLocaleLowerCase("vi")
    const keep = (entry: OwnEntry) =>
      (status === "all" || entry.review_status === status) &&
      (kind === "all" || entry.kind === kind) &&
      (tableId === "all" || String(entry.dataset_id) === tableId) &&
      (!attentionOnly || findings.get(entry.id)!.conflicts > 0 || findings.get(entry.id)!.duplicates > 0) &&
      (!text ||
        [entry.name, entry.definition, userName(entry.user_id), entry.source_question]
          .filter(Boolean)
          .some((value) => value!.toLocaleLowerCase("vi").includes(text)))
    // Groups are judged on every entry, so a conflict still shows when the other side is filtered out.
    return groups
      .map((group) => ({ group, shown: group.entries.filter(keep) }))
      .filter((item) => item.shown.length)
      .sort(
        (a, b) =>
          Number(b.group.conflicts) - Number(a.group.conflicts) ||
          Number(b.group.duplicates) - Number(a.group.duplicates) ||
          b.shown.length - a.shown.length ||
          a.group.name.localeCompare(b.group.name, "vi"),
      )
  }, [groups, findings, query, status, kind, tableId, attentionOnly, userName])

  const open = (entryId: string, promote: PromoteRequest | null = null) =>
    setPanel((current) => ({ entryId, promote, nonce: (current?.nonce ?? 0) + 1 }))
  const filtered = !!query.trim() || status !== "pending" || kind !== "all" || tableId !== "all" || attentionOnly
  const clearFilters = () => {
    setQuery("")
    setStatus("all")
    setKind("all")
    setTableId("all")
    setAttentionOnly(false)
  }
  const selectedDataset = selected ? datasetById.get(selected.dataset_id) : undefined

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Chờ duyệt" value={counts.pending} total={counts.all} />
        <StatTile
          label="Chờ duyệt, có mâu thuẫn"
          value={pending.filter((entry) => findings.get(entry.id)!.conflicts > 0).length}
        />
        <StatTile
          label="Chờ duyệt, có bản trùng"
          value={pending.filter((entry) => findings.get(entry.id)!.duplicates > 0).length}
        />
        <StatTile label="Người dùng đóng góp" value={new Set(entries.map((entry) => entry.user_id)).size} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          aria-label="Tìm tri thức riêng"
          placeholder="Tìm tên, nội dung, người dùng"
          className="w-full sm:w-80"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onSearch={setQuery}
          shortcut="/"
        />
        <div className="max-w-full overflow-x-auto [scrollbar-width:none]">
          <SegmentedControl
            label="Trạng thái duyệt"
            size="sm"
            value={status}
            onValueChange={(value) => setStatus(value as StatusFilter)}
            options={[
              { value: "pending", label: `Chờ duyệt ${counts.pending}` },
              { value: "kept_own", label: `Giữ riêng ${counts.kept_own}` },
              { value: "promoted", label: `Đã vào kho ${counts.promoted}` },
              { value: "all", label: `Tất cả ${counts.all}` },
            ]}
          />
        </div>
        <Select items={KIND_ITEMS} value={kind} onValueChange={(value) => setKind((value ?? "all") as typeof kind)}>
          <SelectTrigger size="sm" aria-label="Loại" className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {KIND_ITEMS.map((item) => (
                <SelectItem key={item.value} value={item.value}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
        {entryTables.length > 1 ? (
          <Select items={tableItems} value={tableId} onValueChange={(value) => setTableId(value ?? "all")}>
            <SelectTrigger size="sm" aria-label="Bảng" className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {tableItems.map((item) => (
                  <SelectItem key={item.value} value={item.value}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        ) : null}
        <div className="flex items-center gap-2">
          <Switch
            id="attention-only"
            checked={attentionOnly}
            onCheckedChange={(checked) => setAttentionOnly(checked)}
          />
          <Label htmlFor="attention-only" className="font-normal">
            Chỉ mục trùng hoặc mâu thuẫn
          </Label>
        </div>
      </div>

      <div className={cn("grid items-start gap-3", selected && "lg:grid-cols-[minmax(0,1fr)_36rem]")}>
        <div className="flex min-w-0 flex-col gap-3">
          {entries.length === 0 ? (
            <div className="rounded-xl border">
              <EmptyState
                scene="inbox"
                title="Chưa có tri thức riêng"
                description={
                  "Khi AI hỏi lại người dùng về một khái niệm chưa có trong kho và họ xác nhận cách hiểu, " +
                  "mục đó sẽ hiện ở đây để bạn duyệt."
                }
              />
            </div>
          ) : visible.length === 0 ? (
            <div className="rounded-xl border">
              <EmptyState
                scene={status === "pending" && !filtered ? "done" : "search"}
                title={status === "pending" && !filtered ? "Đã duyệt hết" : "Không có mục khớp"}
                description={
                  status === "pending" && !filtered
                    ? "Không còn tri thức riêng nào chờ duyệt cho database này."
                    : "Không có mục nào khớp bộ lọc."
                }
                secondaryAction={{ label: "Xem tất cả", onAction: clearFilters }}
              />
            </div>
          ) : (
            visible.map(({ group, shown }) => (
              <GroupCard
                key={group.key}
                group={group}
                shown={shown}
                findings={findings}
                tableName={tableName(group.datasetId)}
                userName={userName}
                selectedId={selected?.id ?? null}
                onOpen={(id) => open(id)}
              />
            ))
          )}
        </div>

        {panel && selected ? (
          // Superset scrolls the window and its navbar scrolls away, so the panel sticks just under the top edge.
          <div
            className={cn(
              "order-first overflow-hidden rounded-xl border",
              "lg:sticky lg:top-3 lg:order-none lg:h-[calc(100svh-1.5rem)]",
            )}
          >
            {panel.promote && selectedDataset ? (
              <PromotePanel
                key={panel.nonce}
                entry={selected}
                dataset={selectedDataset}
                request={panel.promote}
                terms={terms.filter((term) => term.dataset_id === selected.dataset_id)}
                metrics={metrics.filter((metric) => metric.dataset_id === selected.dataset_id)}
                rules={rules.filter((rule) => rule.dataset_id === selected.dataset_id)}
                onClose={() => open(selected.id)}
                onDone={() => open(selected.id)}
              />
            ) : (
              <EntryDetail
                key={panel.nonce}
                entry={selected}
                findings={findings.get(selected.id)!}
                table={tableById.get(selected.dataset_id)}
                userName={userName}
                onClose={() => setPanel(null)}
                onOpenEntry={(id) => {
                  // Opening the other side of a conflict should not land on an empty, filtered list.
                  if (
                    !entries.some((entry) => entry.id === id && (status === "all" || entry.review_status === status))
                  ) {
                    setStatus("all")
                  }
                  open(id)
                }}
                onPromote={(request) => open(selected.id, request)}
                onReload={() => {
                  onReload()
                  open(selected.id)
                }}
              />
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function GroupCard({
  group,
  shown,
  findings,
  tableName,
  userName,
  selectedId,
  onOpen,
}: {
  group: EntryGroup
  shown: OwnEntry[]
  findings: Map<string, Findings>
  tableName: string
  userName: UserName
  selectedId: string | null
  onOpen: (id: string) => void
}) {
  const users = new Set(group.entries.map((entry) => entry.user_id)).size
  const live = group.system.filter((item) => item.state !== "revoked" && item.state !== "inactive")

  return (
    <section className="overflow-hidden rounded-xl border" aria-label={group.name}>
      <header className="flex flex-wrap items-center gap-2 border-b bg-muted/40 px-4 py-2.5">
        <h3 className="mr-auto truncate text-sm font-medium">{group.name}</h3>
        {group.meanings > 1 ? (
          <StatusBadge tone="danger" size="sm" dot>{`${group.meanings} cách hiểu khác nhau`}</StatusBadge>
        ) : null}
        {group.againstCatalog ? (
          <StatusBadge tone="danger" size="sm" dot>
            Khác với kho
          </StatusBadge>
        ) : null}
        {group.meanings === 1 && group.entries.length > 1 ? (
          <StatusBadge tone="primary" size="sm">
            Cùng một cách hiểu
          </StatusBadge>
        ) : null}
        {live.map((item) => {
          const Icon = KINDS[item.kind].icon
          return (
            <Badge key={item.id} variant="outline" className="gap-1" title={SYSTEM_STATES[item.state].label}>
              <Icon />
              Trong kho: {item.name}
            </Badge>
          )
        })}
        {/* The extension compares entries within one dataset, so the group names its table. */}
        <Badge variant="outline" className="max-w-48 gap-1" title={tableName}>
          <Table2Icon />
          <span className="truncate">{tableName}</span>
        </Badge>
        <Badge variant="outline" className="tabular-nums">
          {users} người dùng
        </Badge>
      </header>
      <ul className="flex flex-col divide-y">
        {shown.map((entry) => (
          <li key={entry.id}>
            <EntryRow
              entry={entry}
              findings={findings.get(entry.id)!}
              userName={userName}
              selected={entry.id === selectedId}
              onOpen={() => onOpen(entry.id)}
            />
          </li>
        ))}
      </ul>
    </section>
  )
}

function EntryRow({
  entry,
  findings,
  userName,
  selected,
  onOpen,
}: {
  entry: OwnEntry
  findings: Findings
  userName: UserName
  selected: boolean
  onOpen: () => void
}) {
  const kind = KINDS[entry.kind]
  const status = REVIEW_STATES[entry.review_status]

  return (
    <button
      type="button"
      aria-current={selected || undefined}
      onClick={onOpen}
      className={cn(
        "grid w-full cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5 text-left",
        "outline-none transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 focus-visible:ring-2",
        "focus-visible:ring-ring/50 focus-visible:ring-inset md:grid-cols-[auto_minmax(0,1fr)_minmax(0,1.6fr)_auto]",
        selected && "bg-muted",
      )}
    >
      <span className="flex size-8 items-center justify-center rounded-lg border bg-background text-muted-foreground">
        <kind.icon className="size-4" />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium">{userName(entry.user_id)}</span>
          {findings.conflicts ? (
            <TriangleAlertIcon
              className="size-3.5 shrink-0 text-destructive"
              aria-label={`${findings.conflicts} chỗ khác`}
            />
          ) : findings.duplicates ? (
            <CopyIcon
              className="size-3.5 shrink-0 text-muted-foreground"
              aria-label={`${findings.duplicates} bản trùng`}
            />
          ) : null}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {kind.label} · {entry.name}
        </span>
      </span>
      <span className="hidden truncate text-sm text-muted-foreground md:block" title={entry.definition}>
        {entry.definition}
      </span>
      <StatusBadge tone={status.tone} size="sm" dot>
        {status.label}
      </StatusBadge>
    </button>
  )
}
