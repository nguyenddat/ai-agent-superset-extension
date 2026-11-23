import { type ReactNode, useCallback, useEffect, useMemo, useState } from "react"
import { CircleXIcon, Columns3Icon, EyeIcon, InfoIcon, SaveIcon, SparklesIcon, Undo2Icon } from "lucide-react"

import { TaskProgress } from "@/components/task-progress"
import { toast } from "@/components/toaster"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { ApiError } from "@/lib/api"
import { setLeaveWarning } from "@/lib/navigation"

import { saveColumnDictionaries, saveTableDictionary, useTableDictionary } from "./api"
import { ChangedDot } from "./changed-dot"
import { ColumnsTable } from "./columns-table"
import {
  columnFields,
  columnPayload,
  type Draft,
  draftChangeCount,
  effectiveRole,
  emptyDraft,
  tableFields,
  tablePayload,
  tableProblem,
  withChange,
} from "./draft"
import { TableInfoForm } from "./table-info-form"
import type { CatalogTable } from "./table-structure"
import type { ColumnFields, TableDictionary, TableFields } from "./types"
import { useAutofill } from "./use-autofill"

const COLUMN_ERROR = /^columns\[(\d+)\]/
const LEAVE_WARNING = "Từ điển còn thay đổi chưa lưu. Rời mục này sẽ bỏ các thay đổi đó."

function without<Value>(record: Record<string, Value>, key: string) {
  return Object.fromEntries(Object.entries(record).filter(([entryKey]) => entryKey !== key))
}

type Picker = (label: string) => ReactNode

export function DictionaryEditor({
  datasetId,
  picker,
  fallbackLabel,
  catalogTables,
  onDirtyChange,
}: {
  datasetId: number
  picker: Picker
  fallbackLabel: string
  catalogTables: CatalogTable[]
  onDirtyChange: (dirty: boolean) => void
}) {
  const { data: dictionary, error } = useTableDictionary(datasetId)

  if (dictionary) {
    return (
      <Editor
        dictionary={dictionary}
        picker={picker}
        catalogTables={catalogTables.filter((table) => table.dataset_id !== datasetId)}
        onDirtyChange={onDirtyChange}
      />
    )
  }
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{picker(fallbackLabel)}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {error ? (
          <Alert variant="destructive">
            <CircleXIcon />
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        ) : (
          Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-12" />)
        )}
      </CardContent>
    </Card>
  )
}

function Editor({
  dictionary,
  picker,
  catalogTables,
  onDirtyChange,
}: {
  dictionary: TableDictionary
  picker: Picker
  catalogTables: CatalogTable[]
  onDirtyChange: (dirty: boolean) => void
}) {
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [saving, setSaving] = useState(false)
  const [section, setSection] = useState("columns")
  const [tableError, setTableError] = useState<string | null>(null)
  const [columnErrors, setColumnErrors] = useState<Record<string, string>>({})
  const autofill = useAutofill(dictionary)
  const running = autofill.state.status === "running"
  const changeCount = draftChangeCount(draft)
  const dirty = changeCount > 0

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange])

  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener("beforeunload", warn)
    setLeaveWarning(LEAVE_WARNING)
    return () => {
      window.removeEventListener("beforeunload", warn)
      setLeaveWarning(null)
    }
  }, [dirty])

  const savedTable = useMemo(() => tableFields(dictionary), [dictionary])
  const table = useMemo(() => ({ ...savedTable, ...draft.table }), [savedTable, draft.table])

  const changeTable = <Key extends keyof TableFields>(key: Key, value: TableFields[Key]) =>
    setDraft((current) => ({ ...current, table: withChange(current.table, savedTable, key, value) }))

  const changeColumn = <Key extends keyof ColumnFields>(columnName: string, key: Key, value: ColumnFields[Key]) => {
    const column = dictionary.columns.find((item) => item.column_name === columnName)
    if (!column) return
    setColumnErrors((current) => without(current, columnName))
    setDraft((current) => {
      const changes = withChange(current.columns[columnName] ?? {}, columnFields(column), key, value)
      const others = without(current.columns, columnName)
      return { ...current, columns: Object.keys(changes).length ? { ...others, [columnName]: changes } : others }
    })
  }

  const save = useCallback(async () => {
    if (!dirty || saving) return
    const problem = Object.keys(draft.table).length ? tableProblem(table) : null
    if (problem) {
      setSection("table")
      toast.error(problem)
      return
    }
    const changedColumns = dictionary.columns.filter((column) => draft.columns[column.column_name])
    const items = changedColumns.map((column) => {
      const fields = { ...columnFields(column), ...draft.columns[column.column_name] }
      const role = effectiveRole(column, fields)
      return columnPayload(column, role && role !== "measure" ? { ...fields, aggregations: [] } : fields)
    })
    const blank = items.find((item) => !item.display_name)
    if (blank) {
      setSection("columns")
      setColumnErrors({ [blank.column_name]: "Tên hiển thị không được để trống." })
      toast.error("Có cột chưa có tên hiển thị.")
      return
    }

    setSaving(true)
    setTableError(null)
    setColumnErrors({})
    let tableSaved = false
    try {
      if (Object.keys(draft.table).length) {
        await saveTableDictionary(dictionary.dataset_id, tablePayload(table))
        tableSaved = true
        setDraft((current) => ({ ...current, table: {} }))
      }
      if (items.length) {
        await saveColumnDictionaries(dictionary.dataset_id, items)
        setDraft((current) => ({ ...current, columns: {} }))
      }
      toast.success("Đã lưu từ điển.")
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Không thể lưu từ điển."
      const columnIndex = COLUMN_ERROR.exec(message)?.[1]
      if (columnIndex !== undefined && items[Number(columnIndex)]) {
        setSection("columns")
        setColumnErrors({ [items[Number(columnIndex)].column_name]: message })
      } else if (!tableSaved && Object.keys(draft.table).length) {
        setSection("table")
        setTableError(message)
      }
      toast.error(tableSaved ? `Đã lưu thông tin bảng nhưng chưa lưu được cột: ${message}` : message)
    } finally {
      setSaving(false)
    }
  }, [dictionary, dirty, draft, saving, table])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault()
        void save()
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [save])

  const reset = () => {
    setDraft(emptyDraft)
    setTableError(null)
    setColumnErrors({})
  }

  const autofillButton = (
    <Button variant="outline" disabled={dirty || running || saving} onClick={() => void autofill.start()}>
      {running ? <Spinner data-icon="inline-start" /> : <SparklesIcon data-icon="inline-start" />}
      {running ? "Đang điền..." : "Tự động điền"}
    </Button>
  )

  return (
    <Card size="sm" className="min-w-0">
      <CardHeader>
        <CardTitle className="flex min-w-0 flex-wrap items-center gap-2">
          {picker(dictionary.display_name)}
          {dictionary.display_name !== dictionary.table_name && (
            <span className="truncate font-mono text-xs font-normal text-muted-foreground">
              {dictionary.schema_name ? `${dictionary.schema_name}.` : ""}
              {dictionary.table_name}
            </span>
          )}
          <Badge variant={dictionary.is_saved ? "secondary" : "outline"}>
            {dictionary.is_saved ? "Đã mô tả" : "Chưa mô tả"}
          </Badge>
          {!dictionary.can_edit && (
            <Badge variant="outline">
              <EyeIcon data-icon="inline-start" />
              Chỉ xem
            </Badge>
          )}
        </CardTitle>
        {dictionary.can_edit && (
          <CardAction>
            {dirty ? (
              <Tooltip>
                <TooltipTrigger render={<span tabIndex={0} />}>{autofillButton}</TooltipTrigger>
                <TooltipContent>Lưu hoặc hoàn tác thay đổi trước khi tự động điền.</TooltipContent>
              </Tooltip>
            ) : (
              autofillButton
            )}
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {autofill.state.status !== "idle" && (
          <TaskProgress
            title="Tự động điền từ điển bằng AI"
            status={autofill.state.status}
            phases={["Gợi ý cột", "Gợi ý bảng"]}
            phase={autofill.state.phase}
            startedAt={autofill.state.startedAt}
            stats={[
              { label: `/ ${autofill.state.total} cột đã xử lý`, value: autofill.state.processed },
              ...(autofill.state.failed ? [{ label: "cột chưa có gợi ý", value: autofill.state.failed }] : []),
            ]}
            message="Gợi ý chỉ điền vào ô còn trống và được lưu ngay theo từng nhóm cột."
            onCancel={autofill.cancel}
            onClose={autofill.dismiss}
            errorText={autofill.state.error}
            onRetry={() => void autofill.start()}
          />
        )}

        {/* Viewers read the same form; a disabled fieldset turns every control read-only. */}
        <fieldset disabled={!dictionary.can_edit || running || saving} className="min-w-0">
          <Tabs value={section} onValueChange={(value) => setSection(String(value))} className="min-w-0 gap-3">
            <TabsList variant="line" aria-label="Mục từ điển" className="self-start border-b">
              <TabsTrigger value="table" className="h-8">
                <InfoIcon />
                Thông tin bảng
                {Object.keys(draft.table).length > 0 && <ChangedDot />}
              </TabsTrigger>
              <TabsTrigger value="columns" className="h-8">
                <Columns3Icon />
                Cột
                <Badge variant="secondary" className="ml-auto tabular-nums">
                  {dictionary.columns.length}
                </Badge>
                {Object.keys(draft.columns).length > 0 && <ChangedDot />}
              </TabsTrigger>
            </TabsList>
            <TabsContent value="table" className="min-w-0">
              <TableInfoForm
                fields={table}
                saved={savedTable}
                columns={dictionary.columns}
                catalogTables={catalogTables}
                highlighted={autofill.highlighted.table}
                error={tableError}
                onChange={changeTable}
              />
            </TabsContent>
            <TabsContent value="columns" className="min-w-0 overflow-x-auto">
              <ColumnsTable
                datasetId={dictionary.dataset_id}
                columns={dictionary.columns}
                changes={draft.columns}
                highlighted={autofill.highlighted.columns}
                errors={columnErrors}
                onChange={changeColumn}
              />
            </TabsContent>
          </Tabs>
        </fieldset>

        {dirty && (
          <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-background/95 px-4 py-3 shadow-lg backdrop-blur">
            <span className="text-sm">
              <span className="font-medium tabular-nums">{changeCount}</span> thay đổi chưa lưu
              <span className="hidden text-muted-foreground sm:inline"> · Ctrl/⌘ + S để lưu</span>
            </span>
            <div className="flex gap-2">
              <Button variant="ghost" disabled={saving} onClick={reset}>
                <Undo2Icon data-icon="inline-start" />
                Hoàn tác
              </Button>
              <Button disabled={saving} onClick={() => void save()}>
                {saving ? <Spinner data-icon="inline-start" /> : <SaveIcon data-icon="inline-start" />}
                Lưu thay đổi
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
