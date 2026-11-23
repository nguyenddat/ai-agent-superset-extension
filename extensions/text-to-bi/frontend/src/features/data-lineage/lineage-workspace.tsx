import { useCallback, useMemo, useState } from "react"
import { CircleXIcon, PlusIcon } from "lucide-react"

import { EmptyState } from "@/components/empty-state"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import type { Access } from "@/lib/access"
import { navigate, pageHref, useSearchParams } from "@/lib/navigation"
import { cn } from "@/lib/utils"

import { useBusinessModel } from "../business-model/api"
import type { BusinessModel, LineageEdge } from "../business-model/types"
import { DatabasePicker, NoDatabase, useDatabaseScope } from "../workspace/database-scope"
import { FILL_SCREEN } from "../workspace/workspace-layout"
import { useLineageGraph, useTableColumns, useTransformations } from "./api"
import {
  buildLineage,
  lineageEdges,
  traceColumn,
  traceTable,
  traceTransformation,
  type DetailLevel,
  type Highlight,
} from "./graph"
import { LineageCanvas, type CanvasFocus } from "./lineage-canvas"
import { LineageSidebar, type Selection } from "./lineage-sidebar"
import { TransformationEditor } from "./transformation-editor"
import type { GraphEdge, Transformation } from "./types"

const FRAME = `grid min-h-[560px] gap-3 ${FILL_SCREEN} lg:grid-cols-[19rem_minmax(0,1fr)]`

export function LineageWorkspace({ access }: { access: Access }) {
  const scope = useDatabaseScope()
  const { databaseId } = scope
  const model = useBusinessModel(databaseId)
  const graph = useLineageGraph(databaseId)
  const transformations = useTransformations(databaseId)
  const error = scope.error ?? model.error ?? graph.error ?? transformations.error

  if (error) {
    return (
      <Alert variant="destructive">
        <CircleXIcon />
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    )
  }

  // The user can read no dataset, so there is no database to draw the lineage of.
  if (!scope.isLoading && databaseId === null) return <NoDatabase title="Chưa có bảng để vẽ dòng dữ liệu" />

  if (databaseId === null || !model.data || !graph.data || !transformations.data) {
    return (
      <div className={FRAME}>
        <Skeleton className="hidden rounded-xl lg:block" />
        <Skeleton className="rounded-xl" />
      </div>
    )
  }

  if (model.data.datasets.length === 0) {
    return (
      <div className="flex flex-col gap-3">
        <DatabasePicker section="lineage" />
        <div className="rounded-xl border">
          <EmptyState
            scene="chart"
            title="Chưa có bảng để vẽ dòng dữ liệu"
            description="Tạo dataset cho database này trong Superset, rồi khai báo bảng nào tạo ra bảng nào."
          />
        </div>
      </div>
    )
  }

  return (
    <LineageEditor
      // A new database starts with nothing selected and no editor open.
      key={databaseId}
      databaseId={databaseId}
      canEdit={access.can_edit}
      model={model.data}
      edges={graph.data.edges}
      transformations={transformations.data}
    />
  )
}

type EditorState = { transformationId: string | null; target: number | null; nonce: number }

function LineageEditor({
  databaseId,
  canEdit,
  model,
  edges: lineage,
  transformations,
}: {
  databaseId: number
  canEdit: boolean
  model: BusinessModel
  edges: LineageEdge[]
  transformations: Transformation[]
}) {
  const edges = useMemo<GraphEdge[]>(() => lineageEdges(lineage), [lineage])
  // `?dataset=<id>` (from the overview) opens with that table and its direct neighbours in view.
  const requested = Number(useSearchParams().get("dataset")) || null
  const [detail, setDetail] = useState<DetailLevel>("linked")
  const [selection, setSelection] = useState<Selection | null>(() =>
    requested && edges.some((e) => e.source_table_id === requested || e.target_table_id === requested)
      ? { kind: "table", id: requested }
      : null,
  )
  const [focus, setFocus] = useState<CanvasFocus | null>(() =>
    selection?.kind === "table" ? { tableIds: [...traceTable(edges, selection.id).tables], nonce: 0 } : null,
  )
  const [editor, setEditor] = useState<EditorState | null>(null)

  const tables = useMemo(() => new Map(model.datasets.map((table) => [table.dataset_id, table])), [model.datasets])
  const graphTableIds = useMemo(
    () => [...new Set(edges.flatMap((edge) => [edge.source_table_id, edge.target_table_id]))],
    [edges],
  )
  const { data: columns } = useTableColumns(detail === "tables" ? [] : graphTableIds)
  const { cards, links } = useMemo(
    () => buildLineage(edges, tables, model.layers, detail === "tables" ? undefined : columns, detail),
    [edges, tables, model.layers, columns, detail],
  )
  const columnById = useMemo(
    () => new Map([...(columns?.values() ?? [])].flat().map((c) => [c.column_id, c])),
    [columns],
  )

  const highlight = useMemo<Highlight | null>(() => {
    if (!selection) return null
    if (selection.kind === "table") return traceTable(edges, selection.id)
    if (selection.kind === "transformation") return traceTransformation(edges, selection.id)
    const columnTable = new Map([...columnById].map(([id, column]) => [id, column.table_id]))
    return traceColumn(edges, columnTable, selection.id)
  }, [selection, edges, columnById])

  const select = useCallback(
    (next: Selection | null) => {
      setSelection(next)
      if (!next) return
      const columnTable = new Map([...columnById].map(([id, column]) => [id, column.table_id]))
      const ids = [
        ...(next.kind === "table"
          ? traceTable(edges, next.id)
          : next.kind === "transformation"
            ? traceTransformation(edges, next.id)
            : traceColumn(edges, columnTable, next.id)
        ).tables,
      ]
      if (ids.length) setFocus({ tableIds: ids, nonce: Date.now() })
    },
    [edges, columnById],
  )
  const clearSelection = useCallback(() => setSelection(null), [])

  const names = useMemo(() => new Map(transformations.map((item) => [item.id, item.name])), [transformations])
  const selectionLabel = !selection
    ? null
    : selection.kind === "table"
      ? `Nguồn và đích trực tiếp của ${tables.get(selection.id)?.display_name ?? "bảng"}`
      : selection.kind === "transformation"
        ? `Phép biến đổi: ${names.get(selection.id) ?? ""}`
        : `Cột ${columnById.get(selection.id)?.name ?? ""}: nguồn và nơi dùng`

  const openEditor = (transformationId: string | null, target: number | null = null) => {
    setEditor({ transformationId, target, nonce: Date.now() })
    if (transformationId) setSelection({ kind: "transformation", id: transformationId })
  }
  const editing = editor?.transformationId
    ? (transformations.find((item) => item.id === editor.transformationId) ?? null)
    : null

  return (
    <div className={FRAME}>
      <LineageSidebar
        header={<DatabasePicker section="lineage" />}
        tables={tables}
        transformations={transformations}
        edges={edges}
        selection={selection}
        canEdit={canEdit}
        onSelect={select}
        onCreate={(target) => openEditor(null, target ?? null)}
        onEdit={(id) => openEditor(id)}
      />

      <div className="relative min-h-[560px] overflow-hidden rounded-xl border bg-background">
        {edges.length > 0 ? (
          <LineageCanvas
            cards={cards}
            links={links}
            detail={detail}
            onDetailChange={setDetail}
            selectedTable={selection?.kind === "table" ? selection.id : null}
            selectionLabel={selectionLabel}
            focus={focus}
            state={{
              highlight,
              selectedColumn: selection?.kind === "column" ? selection.id : null,
              transformationName: (id) => (id ? (names.get(id) ?? null) : null),
              onSelectColumn: (id) => select({ kind: "column", id }),
              onOpenTable: (id) => navigate(pageHref({ section: "dictionary", dataset: id })),
            }}
            onSelectTable={(id) => select(id ? { kind: "table", id } : null)}
            onSelectTransformation={(id) => select({ kind: "transformation", id })}
            onClearSelection={clearSelection}
          />
        ) : (
          <div className="flex size-full items-center justify-center p-6">
            <EmptyState
              scene="chart"
              title="Chưa có dòng dữ liệu"
              description={
                "Khai báo phép biến đổi đầu tiên: chọn bảng đích, dán SQL tạo ra nó, hệ thống sẽ nhận bảng nguồn " +
                "và liên kết cột."
              }
              action={
                canEdit ? (
                  <Button onClick={() => openEditor(null)}>
                    <PlusIcon data-icon="inline-start" />
                    Khai báo phép biến đổi
                  </Button>
                ) : undefined
              }
            />
          </div>
        )}

        <div
          className={cn(
            "absolute inset-y-0 right-0 z-10 w-full border-l shadow-2xl transition-transform duration-300 ease-out " +
              "lg:w-[min(46rem,100%)]",
            editor ? "translate-x-0" : "pointer-events-none translate-x-full",
          )}
          aria-hidden={!editor}
        >
          {editor ? (
            <TransformationEditor
              key={editor.nonce}
              databaseId={databaseId}
              tables={model.datasets}
              transformation={editing}
              initialTarget={editor.target}
              onClose={() => setEditor(null)}
              onSaved={(saved) => {
                setEditor(null)
                select({ kind: "transformation", id: saved.id })
              }}
            />
          ) : null}
        </div>
      </div>
    </div>
  )
}
