import { useMemo, useState } from "react"
import { CircleXIcon, DatabaseIcon, PlusIcon, ScaleIcon, TriangleAlertIcon } from "lucide-react"

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
import { FILL_SCREEN } from "../workspace/workspace-layout"
import { refreshRules, useRules } from "./api"
import { domainNames } from "@/features/business-model/domains"
import { describeCondition, ruleState, servingIsStale } from "./labels"
import { RuleDetail } from "./rule-detail"
import { RuleEditor } from "./rule-editor"
import { useRuleRefs, type DatasetInfo, type RuleRefs } from "./rule-refs"
import { RuleStatus } from "./rule-status"
import type { ExpertRule } from "./types"

type StateFilter = "all" | "pending" | "active" | "stale" | "revoked"
type Panel = { ruleId: string | null; mode: "view" | "edit"; nonce: number }

const matchesFilter = (rule: ExpertRule, filter: StateFilter) =>
  filter === "all" ||
  (filter === "pending" && rule.current.status === "draft") ||
  (filter === "active" && rule.is_discoverable) ||
  (filter === "stale" && servingIsStale(rule)) ||
  (filter === "revoked" && rule.current.status === "revoked")

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

// Standalone scopes rules by connection and groups them by table; here a rule belongs to one Superset dataset, chosen
// with the dictionary's picker and kept in `?dataset=`, as the dictionary does.
export function RuleWorkspace({ access }: { access: Access }) {
  const searchParams = useSearchParams()
  const { data: summary, error } = useDictionarySummary()

  const datasets = useMemo(() => (summary ? allDatasets(summary) : []), [summary])
  const requested = Number(searchParams.get("dataset"))
  const current = datasets.find((dataset) => dataset.dataset_id === requested) ?? datasets[0]
  // `?rule=<id>` opens one rule, so other screens can link here.
  const requestedRule = searchParams.get("rule")

  if (error) {
    return (
      <Alert variant="destructive">
        <CircleXIcon />
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    )
  }

  if (!summary) return <WorkspaceSkeleton />

  if (!current) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <DatabaseIcon />
          </EmptyMedia>
          <EmptyTitle>Chưa có dataset để ghi quy tắc</EmptyTitle>
          <EmptyDescription>
            Tạo dataset trong Superset, hoặc nhờ quản trị viên cấp quyền đọc dataset, để bắt đầu ghi quy tắc.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <DatasetRules
      key={current.dataset_id}
      access={access}
      summary={summary}
      dataset={current}
      requestedRule={requestedRule}
    />
  )
}

function DatasetRules({
  access,
  summary,
  dataset,
  requestedRule,
}: {
  access: Access
  summary: DictionarySummary
  dataset: DatasetOption
  requestedRule: string | null
}) {
  const datasetId = dataset.dataset_id
  const info = useMemo<DatasetInfo>(
    () => ({ name: dataset.table_name, displayName: dataset.display_name, schemaName: dataset.schema_name }),
    [dataset.table_name, dataset.display_name, dataset.schema_name],
  )
  const rules = useRules(datasetId)
  const { refs, error: refsError } = useRuleRefs(datasetId, info)
  const error = rules.error ?? refsError

  // An editor with unsaved changes has registered a leave warning, which navigate() asks about first.
  const picker = (
    <TablePicker
      summary={summary}
      datasetId={datasetId}
      label={dataset.display_name}
      onSelect={(next) =>
        next !== datasetId && navigate(pageHref({ section: "rules", dataset: next }), { replace: true })
      }
    />
  )

  if (error) {
    return (
      <div className="flex flex-col gap-3">
        <div className="flex">{picker}</div>
        <Alert variant="destructive">
          <CircleXIcon />
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      </div>
    )
  }

  if (!rules.data || !refs) return <WorkspaceSkeleton />

  return (
    <RuleList
      datasetId={datasetId}
      access={access}
      rules={rules.data}
      refs={refs}
      picker={picker}
      requestedRule={requestedRule}
    />
  )
}

function RuleList({
  datasetId,
  access,
  rules,
  refs,
  picker,
  requestedRule,
}: {
  datasetId: number
  access: Access
  rules: ExpertRule[]
  refs: RuleRefs
  picker: React.ReactNode
  requestedRule: string | null
}) {
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<StateFilter>("all")
  const [panel, setPanel] = useState<Panel | null>(
    requestedRule ? { ruleId: requestedRule, mode: "view", nonce: 0 } : null,
  )

  const selected = panel?.ruleId ? rules.find((rule) => rule.id === panel.ruleId) ?? null : null
  const counts = {
    all: rules.length,
    pending: rules.filter((rule) => matchesFilter(rule, "pending")).length,
    active: rules.filter((rule) => matchesFilter(rule, "active")).length,
    stale: rules.filter((rule) => matchesFilter(rule, "stale")).length,
    revoked: rules.filter((rule) => matchesFilter(rule, "revoked")).length,
  }

  const visible = useMemo(() => {
    const text = query.trim().toLocaleLowerCase("vi")
    const table = refs.table
    return rules
      .filter((rule) => matchesFilter(rule, filter))
      .filter(
        (rule) =>
          !text ||
          [
            rule.name,
            ...domainNames(rule.business_domains),
            rule.current.description,
            table.displayName,
            table.name,
            ...rule.current.examples.map((example) => example.question),
          ]
            .filter(Boolean)
            .some((value) => value!.toLocaleLowerCase("vi").includes(text)),
      )
      .sort((a, b) => a.name.localeCompare(b.name, "vi"))
  }, [rules, query, filter, refs])

  const open = (ruleId: string | null, mode: Panel["mode"]) => setPanel({ ruleId, mode, nonce: Date.now() })
  const filtered = !!query.trim() || filter !== "all"
  const clearFilters = () => {
    setQuery("")
    setFilter("all")
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile label="Tổng quy tắc" value={counts.all} />
        <StatTile label="AI đang áp dụng" value={counts.active} total={counts.all} />
        <StatTile label="Chờ duyệt" value={counts.pending} />
        <StatTile label="Cần cập nhật" value={counts.stale} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {picker}
        <SearchInput
          aria-label="Tìm quy tắc"
          placeholder="Tìm theo tên, mô tả, bảng, câu hỏi"
          className="w-full sm:w-80"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onSearch={setQuery}
          shortcut="/"
        />
        <div className="max-w-full overflow-x-auto [scrollbar-width:none]">
          <SegmentedControl
            label="Trạng thái quy tắc"
            size="sm"
            value={filter}
            onValueChange={(value) => setFilter(value as StateFilter)}
            options={[
              { value: "all", label: `Tất cả ${counts.all}` },
              { value: "pending", label: `Chờ duyệt ${counts.pending}` },
              { value: "active", label: `Đang áp dụng ${counts.active}` },
              { value: "stale", label: `Cần cập nhật ${counts.stale}` },
              { value: "revoked", label: `Đã thu hồi ${counts.revoked}` },
            ]}
          />
        </div>
        {access.can_edit ? (
          <Button className="ml-auto" onClick={() => open(null, "edit")}>
            <PlusIcon data-icon="inline-start" />
            Thêm quy tắc
          </Button>
        ) : null}
      </div>

      <div className={cn("grid items-start gap-3", panel && "lg:grid-cols-[minmax(0,1fr)_36rem]")}>
        <div className="flex min-w-0 flex-col gap-3">
          {rules.length === 0 ? (
            <div className="rounded-xl border">
              <EmptyState
                scene="inbox"
                title="Chưa có quy tắc"
                description={
                  "Ghi lại kinh nghiệm của chuyên gia, như ngày nào được tính là nắng nóng, để AI trả lời theo đúng " +
                  "cách đội bạn hiểu dữ liệu."
                }
                action={
                  access.can_edit ? (
                    <Button onClick={() => open(null, "edit")}>
                      <PlusIcon data-icon="inline-start" />
                      Thêm quy tắc
                    </Button>
                  ) : undefined
                }
              />
            </div>
          ) : visible.length === 0 ? (
            <div className="rounded-xl border">
              <EmptyState
                scene="search"
                title="Không có quy tắc khớp"
                description={
                  query.trim() ? `Không thấy quy tắc nào khớp "${query.trim()}".` : "Không có quy tắc nào khớp bộ lọc."
                }
                secondaryAction={filtered ? { label: "Xóa bộ lọc", onAction: clearFilters } : undefined}
              />
            </div>
          ) : (
            <RuleGroup
              rules={visible}
              refs={refs}
              canEdit={access.can_edit}
              selectedId={panel?.ruleId ?? null}
              onOpen={(id) => open(id, "view")}
              onCreate={() => open(null, "edit")}
            />
          )}
        </div>

        {panel && (panel.mode === "edit" || selected) ? (
          <div
            className={cn(
              "order-first overflow-hidden rounded-xl border lg:sticky lg:top-3 lg:order-none",
              FILL_SCREEN,
            )}
          >
            {panel.mode === "edit" ? (
              <RuleEditor
                key={panel.nonce}
                datasetId={datasetId}
                rules={rules}
                refs={refs}
                rule={selected}
                onClose={() => (selected ? open(selected.id, "view") : setPanel(null))}
                onSaved={(saved) => open(saved.id, "view")}
                onReload={async () => {
                  await refreshRules(datasetId)
                  open(panel.ruleId, "edit")
                }}
              />
            ) : (
              <RuleDetail
                key={panel.nonce}
                datasetId={datasetId}
                rule={selected!}
                refs={refs}
                access={access}
                onClose={() => setPanel(null)}
                onEdit={() => open(selected!.id, "edit")}
                onDeleted={() => setPanel(null)}
              />
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function RuleGroup({
  rules,
  refs,
  canEdit,
  selectedId,
  onOpen,
  onCreate,
}: {
  rules: ExpertRule[]
  refs: RuleRefs
  canEdit: boolean
  selectedId: string | null
  onOpen: (id: string) => void
  onCreate: () => void
}) {
  const { table } = refs

  return (
    <section className="overflow-hidden rounded-xl border" aria-label={table.displayName}>
      <header className="flex items-center gap-3 border-b bg-muted/40 px-4 py-2.5">
        <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2">
          <h3 className="truncate text-sm font-medium">{table.displayName}</h3>
          <span className="truncate font-mono text-xs text-muted-foreground">
            {table.schemaName ? `${table.schemaName}.` : ""}
            {table.name}
          </span>
        </div>
        <Badge variant="outline" className="tabular-nums">
          {rules.length} quy tắc
        </Badge>
        {canEdit ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button variant="ghost" size="icon-sm" aria-label="Thêm quy tắc cho bảng này" onClick={onCreate} />
              }
            >
              <PlusIcon />
            </TooltipTrigger>
            <TooltipContent>Thêm quy tắc cho bảng này</TooltipContent>
          </Tooltip>
        ) : null}
      </header>
      <ul className="flex flex-col divide-y">
        {rules.map((rule) => (
          <li key={rule.id}>
            <RuleRow rule={rule} refs={refs} selected={rule.id === selectedId} onOpen={() => onOpen(rule.id)} />
          </li>
        ))}
      </ul>
    </section>
  )
}

function RuleRow({
  rule,
  refs,
  selected,
  onOpen,
}: {
  rule: ExpertRule
  refs: RuleRefs
  selected: boolean
  onOpen: () => void
}) {
  const { conditions, description } = rule.current
  const first = conditions[0]
  const summary =
    description ??
    (first
      ? describeCondition(
          first,
          refs.columnByName.has(first.column_name) ? first.column_name : `${first.column_name} (đã xóa)`,
        )
      : "")

  return (
    <button
      type="button"
      aria-current={selected || undefined}
      onClick={onOpen}
      className={cn(
        "grid w-full cursor-pointer grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 " +
          "px-4 py-2.5 text-left outline-none transition-colors hover:bg-muted/50 focus-visible:bg-muted/50 " +
          "focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset " +
          "md:grid-cols-[auto_minmax(0,1fr)_minmax(0,1.4fr)_auto]",
        selected && "bg-muted",
        ruleState(rule) === "revoked" && "opacity-60",
      )}
    >
      <span className="flex size-8 items-center justify-center rounded-lg border bg-background text-muted-foreground">
        <ScaleIcon className="size-4" />
      </span>
      <span className="flex min-w-0 flex-col">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium">{rule.name}</span>
          {ruleState(rule) === "changed" && servingIsStale(rule) ? (
            <TriangleAlertIcon
              className="size-3.5 shrink-0 text-muted-foreground"
              aria-label="Bản đang dùng tạm ngừng"
            />
          ) : null}
        </span>
        <span className="truncate text-xs text-muted-foreground">
          {[...domainNames(rule.business_domains), `${conditions.length} điều kiện`].join(" · ")}
        </span>
      </span>
      <span className="hidden truncate text-sm text-muted-foreground md:block" title={summary}>
        {summary}
      </span>
      <RuleStatus rule={rule} size="sm" />
    </button>
  )
}
