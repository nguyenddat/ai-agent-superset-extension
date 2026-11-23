import { useMemo, useState } from "react"
import { ChevronRightIcon, GripVerticalIcon, PencilIcon, PlusIcon, Table2Icon } from "lucide-react"

import { NumberRoll } from "@/components/number-roll"
import { SearchInput } from "@/components/search-input"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"

import { qualifiedName } from "./canvas-nodes"
import { TABLE_DRAG_TYPE, type ColoredDomain } from "./domain-canvas"
import type { ModelTable } from "./types"

type ModelSidebarProps = {
  domains: ColoredDomain[]
  tables: ModelTable[]
  // Domain writes are admin only; without the right the sidebar lists the model and focuses the canvas.
  canEdit: boolean
  onFocusDomain: (domainId: string) => void
  onFocusTable: (datasetId: number) => void
  onCreateDomain: () => void
  onEditDomain: (domainId: string) => void
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg bg-muted/60 px-2.5 py-2">
      <NumberRoll value={value} className="text-lg leading-none font-semibold tabular-nums" />
      <span className="text-[11px] text-muted-foreground">{label}</span>
    </div>
  )
}

function Dot({ color, size = "size-5" }: { color: string; size?: string }) {
  return (
    <span
      className={`flex ${size} shrink-0 items-center justify-center rounded-full text-white`}
      style={{ background: color }}
    >
      <Table2Icon className="size-3" />
    </span>
  )
}

export function ModelSidebar({
  domains,
  tables,
  canEdit,
  onFocusDomain,
  onFocusTable,
  onCreateDomain,
  onEditDomain,
}: ModelSidebarProps) {
  const [query, setQuery] = useState("")
  const byId = useMemo(() => new Map(tables.map((table) => [table.dataset_id, table])), [tables])
  const assigned = useMemo(() => new Set(domains.flatMap(({ domain }) => domain.dataset_ids)), [domains])
  const unassigned = useMemo(
    () =>
      tables
        .filter((table) => !assigned.has(table.dataset_id))
        .sort(
          (a, b) => Number(b.is_classified) - Number(a.is_classified) || a.display_name.localeCompare(b.display_name),
        ),
    [tables, assigned],
  )
  const needle = query.trim().toLowerCase()
  const visible = needle
    ? unassigned.filter((table) =>
        [table.display_name, table.table_name, table.schema ?? ""].some((text) => text.toLowerCase().includes(needle)),
      )
    : unassigned

  return (
    <aside className="flex min-h-0 flex-col overflow-hidden rounded-xl border bg-card">
      <div className="grid grid-cols-3 gap-1.5 p-3">
        <Stat label="Miền" value={domains.length} />
        <Stat label="Bảng đã phân" value={tables.length - unassigned.length} />
        <Stat label="Chưa phân" value={unassigned.length} />
      </div>
      <Separator />

      <section className="flex max-h-[55%] min-h-0 flex-col">
        <header className="flex items-center justify-between px-3 pt-3 pb-1.5">
          <h2 className="text-xs font-medium text-muted-foreground uppercase">Miền nghiệp vụ ({domains.length})</h2>
          {canEdit ? (
            <Button variant="ghost" size="icon-xs" aria-label="Thêm miền" onClick={onCreateDomain}>
              <PlusIcon />
            </Button>
          ) : null}
        </header>
        <ScrollArea className="min-h-0 flex-1">
          <ul className="flex flex-col px-1.5 pb-2">
            {domains.map(({ domain, color }) => {
              const members = domain.dataset_ids.flatMap((id) => byId.get(id) ?? [])
              return (
                <Collapsible key={domain.id} render={<li />} defaultOpen={domains.length <= 4}>
                  <div className="group/row flex items-center rounded-lg hover:bg-muted">
                    <CollapsibleTrigger
                      render={
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          className="ml-0.5 [&[data-panel-open]>svg]:rotate-90"
                          aria-label={`Mở ${domain.name}`}
                        />
                      }
                    >
                      <ChevronRightIcon className="transition-transform" />
                    </CollapsibleTrigger>
                    <button
                      type="button"
                      onClick={() => onFocusDomain(domain.id)}
                      className="flex min-w-0 flex-1 items-center gap-2 py-1.5 pr-1 pl-1 text-left text-sm font-medium"
                    >
                      <span
                        className="size-3 shrink-0 rounded-full ring-2 ring-background"
                        style={{ background: color }}
                      />
                      <span className="truncate">{domain.name}</span>
                      <span className="text-xs font-normal text-muted-foreground tabular-nums">
                        ({members.length})
                      </span>
                    </button>
                    {canEdit ? (
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        className="mr-1 opacity-0 group-hover/row:opacity-100 focus-visible:opacity-100"
                        aria-label={`Sửa miền ${domain.name}`}
                        onClick={() => onEditDomain(domain.id)}
                      >
                        <PencilIcon />
                      </Button>
                    ) : null}
                  </div>
                  <CollapsibleContent render={<ul className="ml-5 flex flex-col border-l pl-2" />}>
                    {members.map((table) => (
                      <li key={table.dataset_id}>
                        <button
                          type="button"
                          onClick={() => onFocusTable(table.dataset_id)}
                          className={
                            "flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13px] " +
                            "hover:bg-muted"
                          }
                        >
                          <Dot color={color} />
                          <span className="truncate">{table.display_name}</span>
                        </button>
                      </li>
                    ))}
                    {members.length === 0 ? (
                      <li className="px-1.5 py-1 text-xs text-muted-foreground">Chưa có bảng.</li>
                    ) : null}
                  </CollapsibleContent>
                </Collapsible>
              )
            })}
            {domains.length === 0 ? (
              <li className="px-2 py-1.5 text-sm text-muted-foreground">Chưa có miền nào.</li>
            ) : null}
          </ul>
        </ScrollArea>
      </section>
      <Separator />

      <section className="flex min-h-0 flex-1 flex-col">
        <header className="flex flex-col gap-2 px-3 pt-3 pb-2">
          <div className="flex items-baseline justify-between">
            <h2 className="text-xs font-medium text-muted-foreground uppercase">Chưa phân miền</h2>
            {canEdit ? <span className="text-[11px] text-muted-foreground">Kéo vào một miền</span> : null}
          </div>
          <SearchInput size="sm" placeholder="Tìm bảng" shortcut="/" debounce={120} onSearch={setQuery} />
        </header>
        <ScrollArea className="min-h-0 flex-1">
          <ul className="flex flex-col gap-0.5 px-2 pb-3">
            {visible.map((table) => (
              <li
                key={table.dataset_id}
                draggable={canEdit}
                onDragStart={(event) => {
                  event.dataTransfer.setData(TABLE_DRAG_TYPE, String(table.dataset_id))
                  event.dataTransfer.effectAllowed = "copy"
                }}
                className={cn(
                  "group/item flex items-center gap-2 rounded-lg px-1.5 py-1.5 hover:bg-muted",
                  canEdit && "cursor-grab active:cursor-grabbing",
                )}
              >
                {canEdit ? (
                  <GripVerticalIcon
                    className="size-3.5 shrink-0 text-muted-foreground/50 group-hover/item:text-muted-foreground"
                  />
                ) : null}
                <Dot color="var(--muted-foreground)" />
                <div className="flex min-w-0 flex-col">
                  <span className="truncate text-[13px]">{table.display_name}</span>
                  <span className="truncate font-mono text-[11px] text-muted-foreground">{qualifiedName(table)}</span>
                </div>
              </li>
            ))}
            {visible.length === 0 ? (
              <li className="px-2 py-4 text-center text-sm text-muted-foreground">
                {unassigned.length === 0 ? "Mọi bảng đã thuộc ít nhất một miền." : "Không có bảng phù hợp."}
              </li>
            ) : null}
          </ul>
        </ScrollArea>
      </section>
    </aside>
  )
}
