import { useRef, useState } from "react"
import { ChevronDownIcon, CircleXIcon, CodeIcon, TableIcon, XIcon } from "lucide-react"

import { Combobox, type ComboboxOption } from "@/components/combobox"
import { SegmentedControl } from "@/components/segmented-control"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { ApiError } from "@/lib/api"
import { cn } from "@/lib/utils"

import { DomainPicker } from "../business-model/domains"
import { useTableDictionary } from "../data-dictionary/api"
import type { DatasetOption } from "../data-dictionary/dataset-groups"
import type { ColumnAggregation, ColumnDictionary } from "../data-dictionary/types"
import { CUSTOM_FORMAT, FORMAT_PRESETS, formatSample, suggestLabel, suggestName } from "../metric-management/labels"
import type { Metric, MetricInput } from "../metric-management/types"

// Standalone promotes a metric through MetricEditor's `promotion` prop. The extension's MetricEditor has no such prop
// yet (and this module may not change it), so this is that editor's create form in promotion mode: the same fields,
// wording and layout, opened with the user's wording and saved through the own-knowledge API. The dataset is fixed:
// the backend always creates the metric on the entry's dataset.

export type MetricPromotion = {
  title: string
  seed: { label: string; description: string }
  create: (input: MetricInput) => Promise<Metric>
}

function datasetOption(dataset: DatasetOption): ComboboxOption {
  const Icon = dataset.dataset_kind === "virtual" ? CodeIcon : TableIcon
  return {
    value: String(dataset.dataset_id),
    label: dataset.display_name,
    description: `${dataset.schema_name ? `${dataset.schema_name}.` : ""}${dataset.table_name}`,
    keywords: [dataset.table_name, dataset.schema_name ?? "", dataset.database_name],
    group: dataset.schema_name ?? "(không có schema)",
    icon: <Icon className="size-4 text-muted-foreground" />,
  }
}

const quote = (name: string) => (/^[a-z_][a-z0-9_]*$/.test(name) ? name : `"${name.replace(/"/g, '""')}"`)

function aggregate(fn: ColumnAggregation, column: string) {
  if (fn === "COUNT_DISTINCT") return `COUNT(DISTINCT ${quote(column)})`
  return `${fn}(${quote(column)})`
}

const nullable = (value: string) => (value.trim() ? value.trim() : null)

export function MetricPromotionEditor({
  dataset,
  metrics,
  promotion,
  onClose,
  onSaved,
}: {
  dataset: DatasetOption
  metrics: Metric[]
  promotion: MetricPromotion
  onClose: () => void
  onSaved: (metric: Metric) => void
}) {
  const datasetId = dataset.dataset_id
  const expressionRef = useRef<HTMLTextAreaElement>(null)

  const [name, setName] = useState("")
  const [nameTouched, setNameTouched] = useState(false)
  const [label, setLabel] = useState(promotion.seed.label)
  // The user's name for the concept is a better label than one guessed from the expression.
  const [labelTouched, setLabelTouched] = useState(true)
  const [expression, setExpression] = useState("")
  const [description, setDescription] = useState(promotion.seed.description)
  const [formatChoice, setFormatChoice] = useState("")
  const [customFormat, setCustomFormat] = useState("")
  const [currency, setCurrency] = useState("")
  const [metricType, setMetricType] = useState("")
  const [warning, setWarning] = useState("")
  const [domainIds, setDomainIds] = useState<string[]>([])
  const [advanced, setAdvanced] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  const [showErrors, setShowErrors] = useState(false)

  const dictionary = useTableDictionary(datasetId)
  const columns = dictionary.data?.dataset_id === datasetId ? dictionary.data.columns : undefined
  const displayName = (column: string) => columns?.find((item) => item.column_name === column)?.display_name
  const format = formatChoice === CUSTOM_FORMAT ? customFormat : formatChoice
  const sample = formatSample(nullable(format), nullable(currency))

  const nameTaken =
    (error?.status === 409 && error.message.startsWith("Tên metric")) ||
    // The backend compares names case-insensitively.
    metrics.some(
      (item) => item.dataset_id === datasetId && item.name.toLowerCase() === name.trim().toLowerCase(),
    )
  const issues = {
    name: !name.trim() ? "Đặt tên kỹ thuật cho metric." : null,
    expression: !expression.trim()
      ? "Viết biểu thức SQL tính metric."
      : expression.includes(";")
        ? "Biểu thức không được chứa dấu chấm phẩy."
        : null,
  }
  const valid = Object.values(issues).every((issue) => !issue) && !nameTaken

  function changeExpression(next: string) {
    setExpression(next)
    if (!nameTouched) setName(suggestName(next) ?? "")
    if (!labelTouched) setLabel(suggestLabel(next, displayName) ?? "")
  }

  // Inserts at the cursor, so a column can go inside a CASE WHEN as easily as into an empty field.
  function insert(text: string) {
    const area = expressionRef.current
    const start = area?.selectionStart ?? expression.length
    const end = area?.selectionEnd ?? expression.length
    changeExpression(expression.slice(0, start) + text + expression.slice(end))
    requestAnimationFrame(() => {
      area?.focus()
      area?.setSelectionRange(start + text.length, start + text.length)
    })
  }

  async function save() {
    setShowErrors(true)
    if (!valid) return
    setBusy(true)
    setError(null)
    try {
      const saved = await promotion.create({
        dataset_id: datasetId,
        name: name.trim(),
        expression: expression.trim(),
        label: nullable(label),
        description: nullable(description),
        format: nullable(format),
        currency: nullable(currency),
        metric_type: nullable(metricType),
        warning_text: nullable(warning),
        business_domain_ids: domainIds,
      })
      onSaved(saved)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, "Không lưu được metric."))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-label="Thêm metric" className="flex size-full min-h-0 flex-col bg-background">
      <header className="flex items-start justify-between gap-3 border-b px-5 py-4">
        <div className="flex flex-col gap-0.5">
          <h2 className="text-base font-medium">{promotion.title}</h2>
          {/* Standalone adds "metric hoạt động ngay khi lưu"; here a new metric waits for approval like a term. */}
          <p className="text-sm text-muted-foreground">
            Người dùng chỉ mô tả bằng lời. Hãy tự viết và kiểm tra biểu thức SQL.
          </p>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Đóng" onClick={onClose}>
          <XIcon />
        </Button>
      </header>

      <ScrollArea className="min-h-0 flex-1">
        <form
          id="metric-promotion-form"
          className="flex flex-col gap-6 px-5 py-5"
          onSubmit={(event) => {
            event.preventDefault()
            void save()
          }}
        >
          <FieldGroup>
            <Field>
              <FieldLabel>Bảng</FieldLabel>
              <Combobox
                label="Bảng"
                placeholder="Chọn bảng chứa dữ liệu"
                searchPlaceholder="Tìm bảng"
                options={[datasetOption(dataset)]}
                value={datasetOption(dataset)}
                onValueChange={() => undefined}
                width={360}
                disabled
              />
            </Field>

            <Field data-invalid={(showErrors && !!issues.expression) || undefined}>
              <FieldLabel htmlFor="metric-expression">Biểu thức SQL</FieldLabel>
              <Textarea
                ref={expressionRef}
                id="metric-expression"
                spellCheck={false}
                rows={4}
                maxLength={10000}
                className="max-h-64 font-mono text-xs"
                placeholder="VD: SUM(doanh_thu) hoặc COUNT(DISTINCT khach_hang_id)"
                aria-invalid={(showErrors && !!issues.expression) || undefined}
                value={expression}
                onChange={(event) => changeExpression(event.target.value)}
              />
              {showErrors && issues.expression ? (
                <FieldError>{issues.expression}</FieldError>
              ) : (
                <FieldDescription>
                  Một biểu thức tổng hợp, không phải câu SELECT. Bấm cột bên dưới để chèn.
                </FieldDescription>
              )}
              <ColumnPicker loading={!columns && !dictionary.error} columns={columns ?? []} onInsert={insert} />
            </Field>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field data-invalid={nameTaken || (showErrors && !!issues.name) || undefined}>
                <FieldLabel htmlFor="metric-name">Tên kỹ thuật</FieldLabel>
                <Input
                  id="metric-name"
                  maxLength={255}
                  spellCheck={false}
                  className="font-mono"
                  placeholder="VD: sum__doanh_thu"
                  aria-invalid={nameTaken || undefined}
                  value={name}
                  onChange={(event) => {
                    setName(event.target.value)
                    setNameTouched(true)
                    if (error?.status === 409) setError(null)
                  }}
                />
                {nameTaken ? (
                  <FieldError>Bảng này đã có metric cùng tên.</FieldError>
                ) : showErrors && issues.name ? (
                  <FieldError>{issues.name}</FieldError>
                ) : null}
              </Field>
              <Field>
                <FieldLabel htmlFor="metric-label">Tên hiển thị</FieldLabel>
                <Input
                  id="metric-label"
                  maxLength={255}
                  placeholder="VD: Tổng doanh thu"
                  value={label}
                  onChange={(event) => {
                    setLabel(event.target.value)
                    setLabelTouched(true)
                  }}
                />
              </Field>
            </div>

            <Field>
              <FieldLabel htmlFor="metric-description">Mô tả</FieldLabel>
              <Textarea
                id="metric-description"
                rows={2}
                placeholder="Metric này đo gì, dùng khi nào. Không bắt buộc."
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </Field>

            <Field>
              <FieldLabel>Miền nghiệp vụ</FieldLabel>
              <DomainPicker value={domainIds} onChange={setDomainIds} />
              <FieldDescription>Một metric có thể thuộc nhiều miền của semantic model.</FieldDescription>
            </Field>
          </FieldGroup>

          <Separator />

          <FieldGroup>
            <Field>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <FieldLabel>Định dạng số</FieldLabel>
                {sample ? (
                  <span className="text-sm text-muted-foreground">
                    Hiển thị: <span className="font-mono text-foreground tabular-nums">{sample}</span>
                  </span>
                ) : null}
              </div>
              <SegmentedControl
                label="Định dạng số"
                size="sm"
                block
                value={formatChoice}
                onValueChange={setFormatChoice}
                options={[
                  ...FORMAT_PRESETS.map((preset) => ({ value: preset.value, label: preset.label })),
                  { value: CUSTOM_FORMAT, label: "Tùy chỉnh" },
                ]}
              />
              {formatChoice === CUSTOM_FORMAT ? (
                <Input
                  aria-label="Định dạng tùy chỉnh"
                  maxLength={128}
                  spellCheck={false}
                  className="font-mono"
                  placeholder="Theo d3-format, VD: ,.1f"
                  value={customFormat}
                  onChange={(event) => setCustomFormat(event.target.value)}
                />
              ) : null}
            </Field>
            <Field className="sm:max-w-48">
              <FieldLabel htmlFor="metric-currency">Đơn vị tiền tệ</FieldLabel>
              <Input
                id="metric-currency"
                maxLength={16}
                placeholder="VD: VND"
                value={currency}
                onChange={(event) => setCurrency(event.target.value)}
              />
            </Field>
          </FieldGroup>

          <Collapsible open={advanced} onOpenChange={setAdvanced}>
            <CollapsibleTrigger render={<Button type="button" variant="ghost" size="sm" className="-ml-2" />}>
              <ChevronDownIcon
                data-icon="inline-start"
                className={cn("transition-transform", !advanced && "-rotate-90")}
              />
              Thêm thông tin
            </CollapsibleTrigger>
            <CollapsibleContent>
              <FieldGroup className="pt-3">
                <Field className="sm:max-w-64">
                  <FieldLabel htmlFor="metric-type">Loại metric</FieldLabel>
                  <Input
                    id="metric-type"
                    maxLength={64}
                    placeholder="VD: sum, count"
                    value={metricType}
                    onChange={(event) => setMetricType(event.target.value)}
                  />
                </Field>
                <Field>
                  <FieldLabel htmlFor="metric-warning">Cảnh báo khi dùng</FieldLabel>
                  <Textarea
                    id="metric-warning"
                    rows={2}
                    placeholder="VD: Chưa gồm đơn hàng bị hủy."
                    value={warning}
                    onChange={(event) => setWarning(event.target.value)}
                  />
                  <FieldDescription>Hiện cạnh metric để người dùng biết giới hạn của con số.</FieldDescription>
                </Field>
              </FieldGroup>
            </CollapsibleContent>
          </Collapsible>

          {error && !nameTaken ? (
            <Alert variant="destructive">
              <CircleXIcon />
              <AlertDescription>{error.message}</AlertDescription>
            </Alert>
          ) : null}
        </form>
      </ScrollArea>

      <footer className="flex flex-wrap items-center gap-2 border-t px-5 py-3">
        <div className="ml-auto flex gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Hủy
          </Button>
          <Button type="submit" form="metric-promotion-form" disabled={busy}>
            {busy ? <Spinner data-icon="inline-start" /> : null}
            Đưa vào kho
          </Button>
        </div>
      </footer>
    </section>
  )
}

type InsertMode = ColumnAggregation | "column"

const INSERT_MODES: { value: InsertMode; label: string }[] = [
  { value: "SUM", label: "SUM" },
  { value: "AVG", label: "AVG" },
  { value: "MIN", label: "MIN" },
  { value: "MAX", label: "MAX" },
  { value: "COUNT_DISTINCT", label: "COUNT DISTINCT" },
  { value: "column", label: "Chỉ tên cột" },
]

const ROLE_ORDER = ["measure", "key", "time", "dimension", "label", "row_kind", "attribute"]

function ColumnPicker({
  loading,
  columns,
  onInsert,
}: {
  loading: boolean
  columns: ColumnDictionary[]
  onInsert: (text: string) => void
}) {
  const [mode, setMode] = useState<InsertMode>("SUM")
  const [query, setQuery] = useState("")
  if (loading) return <Skeleton className="h-28" />

  const term = query.trim().toLowerCase()
  // Measures first: they are what a metric usually adds up.
  const shown = columns
    .filter(
      (column) =>
        !term || column.column_name.toLowerCase().includes(term) || column.display_name.toLowerCase().includes(term),
    )
    .sort((a, b) => ROLE_ORDER.indexOf(a.semantic_role) - ROLE_ORDER.indexOf(b.semantic_role))

  return (
    <div className="flex flex-col gap-2.5 rounded-lg border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">Bấm cột để chèn</span>
        <SegmentedControl
          label="Cách chèn cột"
          size="sm"
          value={mode}
          onValueChange={(value) => setMode(value as InsertMode)}
          options={INSERT_MODES}
        />
      </div>
      <div className="flex items-center gap-2">
        <Input
          aria-label="Lọc cột"
          placeholder="Lọc cột"
          className="h-7 flex-1 text-xs"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Button type="button" variant="outline" size="xs" className="font-mono" onClick={() => onInsert("COUNT(*)")}>
          COUNT(*)
        </Button>
      </div>
      <div className="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto">
        {shown.map((column) => {
          const text = mode === "column" ? quote(column.column_name) : aggregate(mode, column.column_name)
          return (
            <button
              key={column.column_name}
              type="button"
              title={`Chèn ${text} · ${column.display_name} · ${column.data_type}`}
              className="cursor-pointer rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
              onClick={() => onInsert(text)}
            >
              <Badge variant={column.semantic_role === "measure" ? "secondary" : "outline"} className="font-mono">
                {column.column_name}
              </Badge>
            </button>
          )
        })}
        {shown.length === 0 ? <span className="text-xs text-muted-foreground">Không có cột khớp.</span> : null}
      </div>
    </div>
  )
}
