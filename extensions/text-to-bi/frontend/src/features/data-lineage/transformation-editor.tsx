import { useMemo, useState } from "react"
import {
  ArrowRightIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  CircleXIcon,
  EyeIcon,
  PlusIcon,
  SigmaIcon,
  SparklesIcon,
  Table2Icon,
  Trash2Icon,
  WandSparklesIcon,
  XIcon,
} from "lucide-react"

import { Combobox, type ComboboxOption } from "@/components/combobox"
import { SegmentedControl } from "@/components/segmented-control"
import { toast } from "@/components/toaster"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { ApiError } from "@/lib/api"

import type { ModelTable } from "../business-model/types"
import { deleteTransformation, previewSql, readViewSql, saveTransformation, useTableColumns } from "./api"
import { ORIGINS, ROLES, qualifiedName } from "./labels"
import {
  columnId,
  type ColumnDependency,
  type DependencyRole,
  type LineageColumn,
  type Transformation,
  type TransformationOrigin,
} from "./types"

type DepRow = ColumnDependency & { key: string }

type TransformationEditorProps = {
  databaseId: number
  tables: ModelTable[]
  transformation: Transformation | null
  initialTarget: number | null
  onClose: () => void
  onSaved: (transformation: Transformation) => void
}

const NO_TARGET = "__none__"
const NO_SCHEMA = "(không có schema)"
let rowKey = 0
const withKey = (dep: ColumnDependency): DepRow => ({ ...dep, key: `row-${(rowKey += 1)}` })
const depKey = (dep: ColumnDependency) =>
  `${dep.source_dataset_id}|${dep.source_column_name}|${dep.target_column_name ?? ""}|${dep.role}`
const EMPTY_DEP: ColumnDependency = {
  source_dataset_id: 0,
  source_column_name: "",
  target_column_name: null,
  role: "value",
}
const roleItems = ROLES.map((role) => ({ value: role.value, label: role.label }))

function tableOption(table: ModelTable): ComboboxOption {
  // Superset does not say which datasets are views, so standalone's view icon has no counterpart here.
  const Icon = table.table_kind === "aggregate" ? SigmaIcon : Table2Icon
  return {
    value: String(table.dataset_id),
    label: table.display_name,
    description: qualifiedName(table),
    keywords: [table.table_name, table.schema ?? ""],
    group: table.schema ?? NO_SCHEMA,
    icon: <Icon className="size-4 text-muted-foreground" />,
  }
}

const suggestedName = (table: ModelTable) => `Nạp ${table.table_name}`
const asApiError = (e: unknown) => (e instanceof ApiError ? e : new ApiError(0, String(e)))

export function TransformationEditor(props: TransformationEditorProps) {
  const { databaseId, tables, transformation, initialTarget, onClose, onSaved } = props
  const byId = useMemo(() => new Map(tables.map((table) => [table.dataset_id, table])), [tables])
  const options = useMemo(() => tables.map(tableOption), [tables])

  const [targetId, setTargetId] = useState<number | null>(transformation?.target_dataset_id ?? initialTarget)
  const [name, setName] = useState(
    transformation?.name ?? (initialTarget && byId.get(initialTarget) ? suggestedName(byId.get(initialTarget)!) : ""),
  )
  const [nameTouched, setNameTouched] = useState(!!transformation)
  const [description, setDescription] = useState(transformation?.description ?? "")
  const [origin, setOrigin] = useState<TransformationOrigin>(transformation?.origin ?? "manual")
  const [sql, setSql] = useState(transformation?.sql_text ?? "")
  const [sourceIds, setSourceIds] = useState<number[]>(transformation?.source_dataset_ids ?? [])
  const [deps, setDeps] = useState<DepRow[]>(() => (transformation?.dependencies ?? []).map(withKey))
  const [analysis, setAnalysis] = useState<{ warnings: string[]; complete: boolean } | null>(null)
  const [busy, setBusy] = useState<"analyze" | "view" | "save" | "delete" | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [showErrors, setShowErrors] = useState(false)
  // Superset does not tell views apart from tables; a dataset counts as a view once its view SQL has been read (or a
  // saved transformation already uses it), which is what the backend checks before accepting "SQL của view".
  const [views, setViews] = useState<Set<number>>(
    () => new Set(transformation?.origin === "view_sql" ? [transformation.target_dataset_id] : []),
  )

  const target = targetId !== null ? byId.get(targetId) : undefined
  const targetIsView = targetId !== null && views.has(targetId)
  const { data: columns } = useTableColumns(targetId !== null ? [targetId, ...sourceIds] : sourceIds)
  // Columns of a table picked a moment ago may still be loading; matching waits for every one of them.
  const columnsReady = [targetId, ...sourceIds].every((id) => id === null || columns?.has(id))
  const targetColumns = (targetId !== null && columns?.get(targetId)) || []
  const sourceColumns = sourceIds.map((id) => ({ id, table: byId.get(id), columns: columns?.get(id) ?? [] }))
  const sourceColumnById = new Map(
    sourceColumns.flatMap((group) => group.columns).map((column) => [column.column_id, column]),
  )
  const sourceItems = [...sourceColumnById.values()].map((column) => ({ value: column.column_id, label: column.name }))

  const issues = {
    target: targetId === null ? "Chọn bảng đích." : null,
    name: !name.trim() ? "Đặt tên cho phép biến đổi." : null,
    sources: sourceIds.length === 0 ? "Chọn ít nhất một bảng nguồn." : null,
    sql: origin !== "manual" && !sql.trim() ? "Nguồn SQL cần có câu lệnh." : null,
    deps: deps.some((dep) => !dep.source_column_name || (dep.role === "value" && !dep.target_column_name))
      ? "Mỗi liên kết cần cột nguồn; vai trò Giá trị cần cả cột đích."
      : new Set(deps.map(depKey)).size !== deps.length
        ? "Có liên kết cột bị lặp."
        : null,
  }
  const valid = Object.values(issues).every((issue) => !issue)

  function changeTarget(option: ComboboxOption | null) {
    const next = option ? Number(option.value) : null
    setTargetId(next)
    setSourceIds((ids) => ids.filter((id) => id !== next))
    // Target columns belong to the old table, so the links lose them: value links go, the others keep their source.
    setDeps((rows) =>
      rows.flatMap((row) =>
        row.target_column_name ? (row.role === "value" ? [] : [{ ...row, target_column_name: null }]) : [row],
      ),
    )
    if (!nameTouched) setName(next !== null && byId.get(next) ? suggestedName(byId.get(next)!) : "")
    if (origin === "view_sql" && !(next !== null && views.has(next))) setOrigin("sql_job")
    setAnalysis(null)
  }

  function changeSources(picked: ComboboxOption[]) {
    const ids = picked.map((option) => Number(option.value))
    const kept = new Set(ids)
    setSourceIds(ids)
    setDeps((rows) => rows.filter((row) => !row.source_column_name || kept.has(row.source_dataset_id)))
  }

  function mergeDeps(found: ColumnDependency[]) {
    const known = new Set(deps.map(depKey))
    const fresh = found.filter((dep) => !known.has(depKey(dep)))
    setDeps((rows) => [...rows, ...fresh.map(withKey)])
    return fresh.length
  }

  async function analyze(text = sql) {
    if (targetId === null || !text.trim()) return
    setBusy("analyze")
    setError(null)
    try {
      const preview = await previewSql(databaseId, targetId, text)
      const added = preview.source_dataset_ids.filter((id) => !sourceIds.includes(id) && id !== targetId)
      setSourceIds((ids) => [...ids, ...added])
      const links = mergeDeps(preview.dependencies)
      setAnalysis({ warnings: preview.warnings, complete: preview.complete })
      if (origin === "manual") setOrigin("sql_job")
      toast.success(
        `Đã nhận ${preview.source_dataset_ids.length} bảng nguồn và ${preview.dependencies.length} liên kết cột.`,
        {
          description:
            added.length || links
              ? `Thêm mới ${added.length} bảng, ${links} liên kết. Kiểm tra lại trước khi lưu.`
              : "Không có gì mới so với khai báo hiện tại.",
        },
      )
    } catch (e) {
      setError(asApiError(e))
    } finally {
      setBusy(null)
    }
  }

  async function loadViewSql() {
    if (targetId === null) return
    setBusy("view")
    setError(null)
    try {
      const { sql_text } = await readViewSql(databaseId, targetId)
      setViews((known) => new Set(known).add(targetId))
      setSql(sql_text)
      setOrigin("view_sql")
      setBusy(null)
      await analyze(sql_text)
    } catch (e) {
      setError(asApiError(e))
      setBusy(null)
    }
  }

  function matchByName() {
    const found: ColumnDependency[] = []
    for (const column of targetColumns) {
      const source = sourceColumns
        .flatMap((group) => group.columns)
        .find((candidate) => candidate.name.toLowerCase() === column.name.toLowerCase())
      if (source) {
        found.push({
          source_dataset_id: source.table_id,
          source_column_name: source.name,
          target_column_name: column.name,
          role: "value",
        })
      }
    }
    const added = mergeDeps(found)
    if (added) toast.success(`Đã ghép ${added} cột trùng tên.`)
    else {
      toast.info(
        found.length ? "Các cột trùng tên đã được ghép từ trước." : "Không có cột nào trùng tên giữa nguồn và đích.",
      )
    }
  }

  const updateDep = (key: string, change: Partial<ColumnDependency>) =>
    setDeps((rows) => rows.map((row) => (row.key === key ? { ...row, ...change } : row)))

  async function save() {
    setShowErrors(true)
    if (!valid || targetId === null) return
    setBusy("save")
    setError(null)
    try {
      const saved = await saveTransformation(
        databaseId,
        {
          target_dataset_id: targetId,
          name: name.trim(),
          description: description.trim() || null,
          sql_text: sql.trim() || null,
          origin,
          source_dataset_ids: sourceIds,
          dependencies: deps.map(({ source_dataset_id, source_column_name, target_column_name, role }) => ({
            source_dataset_id,
            source_column_name,
            target_column_name,
            role,
          })),
        },
        transformation?.id,
      )
      toast.success(transformation ? `Đã cập nhật "${saved.name}".` : `Đã khai báo "${saved.name}".`)
      onSaved(saved)
    } catch (e) {
      setError(asApiError(e))
    } finally {
      setBusy(null)
    }
  }

  async function remove() {
    if (!transformation) return
    setBusy("delete")
    try {
      await deleteTransformation(databaseId, transformation.id)
      toast.success(`Đã xóa "${transformation.name}".`)
      onClose()
    } catch (e) {
      setError(asApiError(e))
      setBusy(null)
    }
  }

  const nameTaken = error?.status === 409
  const columnLabel = (column: LineageColumn) => (
    <span className="flex min-w-0 items-center gap-2">
      <span className="truncate font-mono text-xs">{column.name}</span>
      <span className="shrink-0 font-mono text-[10px] text-muted-foreground">{column.data_type}</span>
    </span>
  )
  const removeDep = (key: string) => setDeps((rows) => rows.filter((item) => item.key !== key))

  return (
    <section
      aria-label={transformation ? "Sửa phép biến đổi" : "Khai báo phép biến đổi"}
      className="flex size-full min-h-0 flex-col bg-background"
    >
      <header className="flex items-start justify-between gap-3 border-b px-5 py-4">
        <div className="flex flex-col gap-0.5">
          <h2 className="text-base font-medium">{transformation ? "Sửa phép biến đổi" : "Khai báo phép biến đổi"}</h2>
          <p className="text-sm text-muted-foreground">
            Bảng nào tạo ra bảng nào, bằng SQL gì và cột nào lấy từ cột nào.
          </p>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Đóng" onClick={onClose}>
          <XIcon />
        </Button>
      </header>

      <ScrollArea className="min-h-0 flex-1">
        <form
          id="transformation-form"
          className="flex flex-col gap-6 px-5 py-5"
          onSubmit={(event) => {
            event.preventDefault()
            void save()
          }}
        >
          <FieldGroup>
            <Field data-invalid={(showErrors && !!issues.target) || undefined}>
              <FieldLabel>Bảng đích</FieldLabel>
              <Combobox
                label="Bảng đích"
                placeholder="Chọn bảng được tạo ra"
                searchPlaceholder="Tìm bảng"
                options={options}
                value={target ? tableOption(target) : null}
                onValueChange={changeTarget}
                width={360}
              />
              {showErrors && issues.target ? <FieldError>{issues.target}</FieldError> : null}
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field data-invalid={nameTaken || (showErrors && !!issues.name) || undefined}>
                <FieldLabel htmlFor="transformation-name">Tên</FieldLabel>
                <Input
                  id="transformation-name"
                  maxLength={255}
                  placeholder="VD: Nạp fact_tong_hop_thoi_tiet"
                  value={name}
                  aria-invalid={nameTaken || undefined}
                  onChange={(event) => {
                    setName(event.target.value)
                    setNameTouched(true)
                    if (nameTaken) setError(null)
                  }}
                />
                {nameTaken ? (
                  <FieldError>Bảng đích đã có phép biến đổi cùng tên.</FieldError>
                ) : showErrors && issues.name ? (
                  <FieldError>{issues.name}</FieldError>
                ) : null}
              </Field>
              <Field>
                <FieldLabel htmlFor="transformation-description">Mô tả</FieldLabel>
                <Input
                  id="transformation-description"
                  placeholder="Không bắt buộc"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </Field>
            </div>
          </FieldGroup>

          <Separator />

          <FieldGroup>
            <Field data-invalid={(showErrors && !!issues.sql) || undefined}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <FieldLabel htmlFor="transformation-sql">SQL tạo bảng đích</FieldLabel>
                <SegmentedControl
                  label="Nguồn khai báo"
                  size="sm"
                  value={origin}
                  onValueChange={(value) => setOrigin(value as TransformationOrigin)}
                  options={ORIGINS.map((item) => ({
                    value: item.value,
                    label: item.label,
                    disabled: item.value === "view_sql" && !targetIsView,
                  }))}
                />
              </div>
              <Textarea
                id="transformation-sql"
                spellCheck={false}
                rows={9}
                className="max-h-80 font-mono text-xs"
                placeholder={
                  "SELECT q.thanh_pho_id, AVG(g.gia_tri) AS gia_tri_tb\nFROM tb_quan_sat_thoi_tiet q\n" +
                  "JOIN tb_gia_tri_quan_sat g ON g.quan_sat_id = q.quan_sat_id\nGROUP BY q.thanh_pho_id"
                }
                value={sql}
                onChange={(event) => {
                  setSql(event.target.value)
                  setAnalysis(null)
                }}
              />
              {showErrors && issues.sql ? (
                <FieldError>{issues.sql}</FieldError>
              ) : (
                <FieldDescription>
                  Dán câu SELECT tạo ra bảng đích rồi bấm Phân tích: hệ thống nhận bảng nguồn và đề xuất liên kết
                  cột. SQL chỉ được lưu, không bao giờ được chạy.
                </FieldDescription>
              )}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={targetId === null || !sql.trim() || busy !== null}
                  onClick={() => void analyze()}
                >
                  {busy === "analyze" ? (
                    <Spinner data-icon="inline-start" />
                  ) : (
                    <SparklesIcon data-icon="inline-start" />
                  )}
                  Phân tích SQL
                </Button>
                {/* Superset cannot tell a view from a table up front, so the button shows for any target and the
                    backend answers when the dataset is not a view. */}
                {target ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={busy !== null}
                    onClick={() => void loadViewSql()}
                  >
                    {busy === "view" ? <Spinner data-icon="inline-start" /> : <EyeIcon data-icon="inline-start" />}
                    Đọc SQL của view
                  </Button>
                ) : null}
              </div>
            </Field>

            {analysis ? (
              analysis.warnings.length > 0 ? (
                <Alert>
                  <CircleAlertIcon />
                  <AlertTitle>Cần khai báo thêm bằng tay</AlertTitle>
                  <AlertDescription>
                    <ul className="list-disc pl-4">
                      {analysis.warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              ) : (
                <Alert>
                  <CircleCheckIcon />
                  <AlertDescription>
                    Bộ phân tích không gặp cấu trúc nào chưa hỗ trợ. Vẫn nên rà lại liên kết bên dưới.
                  </AlertDescription>
                </Alert>
              )
            ) : null}
          </FieldGroup>

          <Separator />

          <FieldGroup>
            <Field data-invalid={(showErrors && !!issues.sources) || undefined}>
              <FieldLabel>Bảng nguồn</FieldLabel>
              <Combobox
                multiple
                label="Bảng nguồn"
                placeholder="Chọn các bảng cung cấp dữ liệu"
                searchPlaceholder="Tìm bảng"
                options={options.filter((option) => option.value !== String(targetId))}
                value={sourceIds.flatMap((id) => (byId.get(id) ? [tableOption(byId.get(id)!)] : []))}
                onValueChange={changeSources}
                width={360}
              />
              {showErrors && issues.sources ? <FieldError>{issues.sources}</FieldError> : null}
            </Field>

            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-medium">Liên kết cột</h3>
                  <Badge variant="secondary">{deps.length}</Badge>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={!columnsReady || !targetColumns.length || sourceIds.length === 0}
                    onClick={matchByName}
                    title="Thêm liên kết Giá trị giữa các cột cùng tên ở nguồn và đích"
                  >
                    {columnsReady ? (
                      <WandSparklesIcon data-icon="inline-start" />
                    ) : (
                      <Spinner data-icon="inline-start" />
                    )}
                    Ghép cột trùng tên
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={sourceIds.length === 0}
                    onClick={() => setDeps((rows) => [...rows, withKey(EMPTY_DEP)])}
                  >
                    <PlusIcon data-icon="inline-start" />
                    Thêm liên kết
                  </Button>
                </div>
              </div>

              {deps.length === 0 ? (
                <p className="rounded-lg border border-dashed px-4 py-5 text-center text-sm text-muted-foreground">
                  Chưa có liên kết cột. Liên kết không bắt buộc, nhưng giúp lần ngược được từng cột về nguồn.
                </p>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <div
                    className={
                      "hidden grid-cols-[minmax(0,1fr)_6.5rem_1rem_minmax(0,1fr)_2rem] gap-2 px-1 text-[11px] " +
                      "font-medium text-muted-foreground uppercase sm:grid"
                    }
                  >
                    <span>Cột nguồn</span>
                    <span>Vai trò</span>
                    <span />
                    <span>Cột đích</span>
                    <span />
                  </div>
                  {deps.map((row) => {
                    const needsTarget = row.role === "value" && !row.target_column_name
                    const duplicate = deps.some((other) => other.key !== row.key && depKey(other) === depKey(row))
                    const targetItems = [
                      { value: NO_TARGET, label: row.role === "value" ? "Chọn cột đích" : "Cả bảng đích" },
                      ...targetColumns.map((column) => ({ value: column.name, label: column.name })),
                    ]
                    return (
                      <div
                        key={row.key}
                        className={
                          "grid grid-cols-[minmax(0,1fr)_2rem] items-center gap-2 rounded-lg border p-2 " +
                          "sm:grid-cols-[minmax(0,1fr)_6.5rem_1rem_minmax(0,1fr)_2rem] sm:border-0 sm:p-0"
                        }
                        data-invalid={
                          (showErrors && (needsTarget || duplicate || !row.source_column_name)) || undefined
                        }
                      >
                        <Select
                          items={sourceItems}
                          value={
                            row.source_column_name ? columnId(row.source_dataset_id, row.source_column_name) : null
                          }
                          onValueChange={(value: string | null) => {
                            const column = value ? sourceColumnById.get(value) : undefined
                            if (column) {
                              updateDep(row.key, {
                                source_dataset_id: column.table_id,
                                source_column_name: column.name,
                              })
                            }
                          }}
                        >
                          <SelectTrigger
                            size="sm"
                            className="w-full"
                            aria-label="Cột nguồn"
                            aria-invalid={(showErrors && !row.source_column_name) || duplicate || undefined}
                          >
                            {/* Radix showed the picked item's text (name and type); Base UI shows the items label,
                                so the trigger renders the same content itself. A column whose dataset's columns
                                are still loading shows its name meanwhile. */}
                            <SelectValue>
                              {(value: string | null) => {
                                const column = value ? sourceColumnById.get(value) : undefined
                                if (column) return columnLabel(column)
                                return value ? row.source_column_name : "Chọn cột nguồn"
                              }}
                            </SelectValue>
                          </SelectTrigger>
                          <SelectContent>
                            {sourceColumns.map(({ id, table, columns: list }) => (
                              <SelectGroup key={id}>
                                <SelectLabel>{table?.display_name}</SelectLabel>
                                {list.map((column) => (
                                  <SelectItem key={column.column_id} value={column.column_id}>
                                    {columnLabel(column)}
                                  </SelectItem>
                                ))}
                              </SelectGroup>
                            ))}
                          </SelectContent>
                        </Select>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          className="sm:hidden"
                          aria-label="Xóa liên kết"
                          onClick={() => removeDep(row.key)}
                        >
                          <Trash2Icon />
                        </Button>
                        <Select
                          items={roleItems}
                          value={row.role}
                          onValueChange={(value: DependencyRole | null) => {
                            if (value) updateDep(row.key, { role: value })
                          }}
                        >
                          <SelectTrigger size="sm" className="w-full" aria-label="Vai trò">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectGroup>
                              {ROLES.map((role) => (
                                <SelectItem key={role.value} value={role.value} title={role.hint}>
                                  {role.label}
                                </SelectItem>
                              ))}
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                        <ArrowRightIcon className="hidden size-4 text-muted-foreground sm:block" />
                        <Select
                          items={targetItems}
                          value={row.target_column_name ?? NO_TARGET}
                          onValueChange={(value: string | null) =>
                            updateDep(row.key, { target_column_name: !value || value === NO_TARGET ? null : value })
                          }
                        >
                          <SelectTrigger
                            size="sm"
                            className="col-span-2 w-full sm:col-span-1"
                            aria-label="Cột đích"
                            aria-invalid={(showErrors && needsTarget) || duplicate || undefined}
                          >
                            <SelectValue>
                              {(value: string) => {
                                if (value === NO_TARGET) {
                                  return (
                                    <span className="text-muted-foreground">
                                      {row.role === "value" ? "Chọn cột đích" : "Cả bảng đích"}
                                    </span>
                                  )
                                }
                                const column = targetColumns.find((item) => item.name === value)
                                return column ? columnLabel(column) : value
                              }}
                            </SelectValue>
                          </SelectTrigger>
                          <SelectContent>
                            <SelectGroup>
                              <SelectItem value={NO_TARGET} disabled={row.role === "value"}>
                                <span className="text-muted-foreground">
                                  {row.role === "value" ? "Chọn cột đích" : "Cả bảng đích"}
                                </span>
                              </SelectItem>
                            </SelectGroup>
                            <SelectGroup>
                              <SelectLabel>{target?.display_name}</SelectLabel>
                              {targetColumns.map((column) => (
                                <SelectItem key={column.column_id} value={column.name}>
                                  {columnLabel(column)}
                                </SelectItem>
                              ))}
                            </SelectGroup>
                          </SelectContent>
                        </Select>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          className="hidden sm:inline-flex"
                          aria-label="Xóa liên kết"
                          onClick={() => removeDep(row.key)}
                        >
                          <Trash2Icon />
                        </Button>
                      </div>
                    )
                  })}
                </div>
              )}
              {showErrors && issues.deps ? <p className="text-sm text-destructive">{issues.deps}</p> : null}
            </div>
          </FieldGroup>

          {error && !nameTaken ? (
            <Alert variant="destructive">
              <CircleXIcon />
              <AlertDescription>{error.message}</AlertDescription>
            </Alert>
          ) : null}
        </form>
      </ScrollArea>

      <footer className="flex flex-wrap items-center gap-2 border-t px-5 py-3">
        {transformation ? (
          confirmDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-sm">Xóa phép biến đổi này?</span>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                disabled={busy !== null}
                onClick={() => void remove()}
              >
                {busy === "delete" ? <Spinner data-icon="inline-start" /> : null}
                Xóa
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
                Giữ lại
              </Button>
            </div>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-destructive"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2Icon data-icon="inline-start" />
              Xóa
            </Button>
          )
        ) : null}
        <div className="ml-auto flex gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Hủy
          </Button>
          <Button type="submit" form="transformation-form" disabled={busy !== null}>
            {busy === "save" ? <Spinner data-icon="inline-start" /> : null}
            {transformation ? "Lưu thay đổi" : "Lưu phép biến đổi"}
          </Button>
        </div>
      </footer>
    </section>
  )
}
