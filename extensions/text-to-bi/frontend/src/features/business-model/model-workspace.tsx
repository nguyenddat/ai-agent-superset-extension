import { useCallback, useMemo, useState } from "react"
import { CircleXIcon, PlusIcon } from "lucide-react"

import { EmptyState } from "@/components/empty-state"
import { toast } from "@/components/toaster"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import type { Access } from "@/lib/access"

import { DatabasePicker, NoDatabase, useDatabaseScope } from "../workspace/database-scope"
import { FILL_SCREEN } from "../workspace/workspace-layout"
import { refreshModel, updateDomain, updateModel, useBusinessModel } from "./api"
import { DomainCanvas, regionNodeId, tableNodeId, type CanvasFocus, type ColoredDomain } from "./domain-canvas"
import { DomainDialog } from "./domain-dialog"
import { ModelSidebar } from "./model-sidebar"
import type { BusinessDomain, BusinessModel } from "./types"
import { domainColor } from "./venn-layout"

const FRAME = `grid min-h-[560px] gap-3 ${FILL_SCREEN} lg:grid-cols-[17rem_minmax(0,1fr)]`
const HINT = "hidden rounded-lg bg-background/80 px-2.5 py-1.5 text-xs text-muted-foreground backdrop-blur md:block"

// Standalone shows the connection in its page header; the extension picks the database in the section itself.
// Above the content the trigger keeps its -ml-2, so its label lines up with the content's edge like TablePicker's.
function PickerRow() {
  return (
    <div className="flex min-h-8 items-center">
      <DatabasePicker section="model" />
    </div>
  )
}

export function ModelWorkspace({ access }: { access: Access }) {
  const { databaseId, isLoading: scopeLoading, error: scopeError } = useDatabaseScope()
  const { data: model, error } = useBusinessModel(databaseId)

  if (scopeError || error) {
    return (
      <div className="flex flex-col gap-3">
        {scopeError ? null : <PickerRow />}
        <Alert variant="destructive">
          <CircleXIcon />
          <AlertDescription>{(scopeError ?? error)!.message}</AlertDescription>
        </Alert>
      </div>
    )
  }

  if (!scopeLoading && databaseId === null) return <NoDatabase title="Chưa có bảng để mô hình hóa" />

  if (!model || model.database_id !== databaseId) {
    return (
      <div className={FRAME}>
        <Skeleton className="hidden rounded-xl lg:block" />
        <Skeleton className="rounded-xl" />
      </div>
    )
  }

  if (model.datasets.length === 0) {
    return (
      <div className="flex flex-col gap-3">
        <PickerRow />
        <div className="rounded-xl border">
          <EmptyState
            scene="chart"
            title="Chưa có bảng để mô hình hóa"
            description={
              "Tạo dataset trong Superset cho database này để lấy danh sách bảng, " +
              "rồi gom chúng vào các miền nghiệp vụ."
            }
          />
        </div>
      </div>
    )
  }

  // Keyed so a switch of database starts with no focus and a closed dialog.
  return <ModelEditor key={model.database_id} model={model} canEdit={access.is_admin} />
}

function ModelEditor({ model, canEdit }: { model: BusinessModel; canEdit: boolean }) {
  const databaseId = model.database_id
  const [focus, setFocus] = useState<CanvasFocus | null>(null)
  const [dialog, setDialog] = useState<{ open: boolean; domain: BusinessDomain | null }>({ open: false, domain: null })

  const domains = useMemo<ColoredDomain[]>(
    () => model.domains.map((domain, index) => ({ domain, color: domainColor(domain, index) })),
    [model.domains],
  )
  const tableIds = useMemo(() => new Set(model.datasets.map((table) => table.dataset_id)), [model.datasets])
  const tableName = (datasetId: number) =>
    model.datasets.find((table) => table.dataset_id === datasetId)?.display_name ?? ""

  // Writes the members of several domains at once: the canvas shows the change at once and goes back if a write fails.
  async function applyMembers(members: Map<string, number[]>) {
    const written = new Map(model.domains.map((domain) => [domain.id, domain]))
    await updateModel(databaseId, (current) => ({
      ...current,
      domains: current.domains.map((domain) =>
        members.has(domain.id) ? { ...domain, dataset_ids: members.get(domain.id)! } : domain,
      ),
    }))
    try {
      await Promise.all(
        [...members].map(([domainId, dataset_ids]) => {
          const { name, description, color } = written.get(domainId)!
          return updateDomain(domainId, { name, description, color, dataset_ids }, tableIds)
        }),
      )
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      await refreshModel(databaseId)
    }
  }

  function setTableDomains(datasetId: number, domainIds: string[]) {
    if (!canEdit) return
    const wanted = new Set(domainIds)
    const changed = model.domains.filter((domain) => domain.dataset_ids.includes(datasetId) !== wanted.has(domain.id))
    if (changed.length === 0) return
    const members = new Map(
      changed.map((domain) => [
        domain.id,
        wanted.has(domain.id)
          ? [...domain.dataset_ids, datasetId]
          : domain.dataset_ids.filter((id) => id !== datasetId),
      ]),
    )
    const names = model.domains.filter((domain) => wanted.has(domain.id)).map((domain) => domain.name)
    const before = new Map(changed.map((domain) => [domain.id, domain.dataset_ids]))
    void applyMembers(members)
    toast.success(
      names.length > 0
        ? `"${tableName(datasetId)}" giờ thuộc ${names.map((name) => `"${name}"`).join(" và ")}.`
        : `Đã bỏ "${tableName(datasetId)}" khỏi mọi miền.`,
      { action: { label: "Hoàn tác", onClick: () => void applyMembers(before) } },
    )
  }

  const editDomain = useCallback((domain: BusinessDomain) => setDialog({ open: true, domain }), [])
  const createDomain = () => setDialog({ open: true, domain: null })
  const domainById = (domainId: string) => model.domains.find((domain) => domain.id === domainId)!

  return (
    <div className={FRAME}>
      <ModelSidebar
        domains={domains}
        tables={model.datasets}
        canEdit={canEdit}
        onFocusTable={(datasetId) => setFocus({ nodeIds: [tableNodeId(datasetId)], nonce: Date.now() })}
        onFocusDomain={(domainId) => setFocus({ nodeIds: [regionNodeId(domainId)], nonce: Date.now() })}
        onCreateDomain={createDomain}
        onEditDomain={(domainId) => editDomain(domainById(domainId))}
      />

      <div className="relative min-h-[560px] overflow-hidden rounded-xl border bg-background">
        {domains.length > 0 ? (
          <DomainCanvas
            model={model}
            domains={domains}
            focus={focus}
            canEdit={canEdit}
            onEditDomain={editDomain}
            onSetDomains={setTableDomains}
          />
        ) : (
          <div className="flex size-full items-center justify-center">
            <EmptyState
              scene="inbox"
              title="Chưa có miền nghiệp vụ"
              description={
                canEdit
                  ? "Tạo miền đầu tiên rồi kéo các bảng ở cột bên trái vào vùng của miền."
                  : "Quản trị viên chưa tạo miền nghiệp vụ nào cho các bảng này."
              }
              action={
                canEdit ? (
                  <Button onClick={createDomain}>
                    <PlusIcon data-icon="inline-start" />
                    Thêm miền nghiệp vụ
                  </Button>
                ) : undefined
              }
            />
          </div>
        )}
        <div className="pointer-events-none absolute inset-x-3 top-3 flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <div className="pointer-events-auto min-w-0 rounded-lg bg-background/80 backdrop-blur">
              {/* The trigger's own padding, also given to the plain name shown when there is a single database. */}
              <DatabasePicker section="model" className="ml-0 px-2 py-1" />
            </div>
            {domains.length > 0 ? (
              <p className={HINT}>
                {canEdit
                  ? "Kéo bảng vào vùng của miền, thả vào chỗ giao nhau để thuộc cả hai miền · nhấp đúp để mở từ điển"
                  : "Chỉ quản trị viên được sửa miền nghiệp vụ · nhấp đúp để mở từ điển"}
              </p>
            ) : null}
          </div>
          {domains.length > 0 && canEdit ? (
            <div className="pointer-events-auto ml-auto flex items-center gap-2">
              <Button size="sm" onClick={createDomain}>
                <PlusIcon data-icon="inline-start" />
                Thêm miền
              </Button>
            </div>
          ) : null}
        </div>
      </div>

      {canEdit ? (
        <DomainDialog
          open={dialog.open}
          domain={dialog.domain}
          tables={model.datasets}
          usedColors={domains.map((item) => item.color)}
          onOpenChange={(open) => setDialog((current) => ({ ...current, open }))}
          onSaved={() => void refreshModel(databaseId)}
        />
      ) : null}
    </div>
  )
}
