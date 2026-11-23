import { useState } from "react"
import { ChevronRightIcon, ChevronsDownUpIcon, ChevronsUpDownIcon, LinkIcon, SearchIcon } from "lucide-react"

import { TagInput } from "@/components/tag-input"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Field, FieldError, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

import { ChangedDot } from "./changed-dot"
import { columnFields, effectiveRole } from "./draft"
import { columnAggregations, roleLabel, semanticRoles, temporalKinds } from "./labels"
import { ReferencePicker } from "./reference-picker"
import type { ColumnAggregation, ColumnDictionary, ColumnFields, SemanticRole, TemporalKind } from "./types"

const AUTO = "auto"
const NONE = "none"

const filters = {
  all: { label: "Tất cả", match: () => true },
  unsaved: { label: "Chưa lưu", match: (column: ColumnDictionary) => !column.is_saved },
  undescribed: { label: "Trống mô tả", match: (column: ColumnDictionary) => !column.description },
}
type Filter = keyof typeof filters

type ColumnChange = <Key extends keyof ColumnFields>(columnName: string, key: Key, value: ColumnFields[Key]) => void

type ColumnsTableProps = {
  datasetId: number
  columns: ColumnDictionary[]
  changes: Record<string, Partial<ColumnFields>>
  highlighted: Set<string>
  errors: Record<string, string>
  onChange: ColumnChange
}

export function ColumnsTable({ datasetId, columns, changes, highlighted, errors, onChange }: ColumnsTableProps) {
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState<Filter>("all")
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const search = query.trim().toLowerCase()
  const visible = columns.filter(
    (column) =>
      filters[filter].match(column) &&
      (!search ||
        column.column_name.toLowerCase().includes(search) ||
        (changes[column.column_name]?.display_name ?? column.display_name).toLowerCase().includes(search)),
  )
  const allExpanded = visible.length > 0 && visible.every((column) => expanded.has(column.column_name))

  const toggle = (columnName: string, open: boolean) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (open) next.add(columnName)
      else next.delete(columnName)
      return next
    })

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <InputGroup className="sm:max-w-xs">
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput
            placeholder="Lọc cột..."
            aria-label="Lọc cột"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </InputGroup>
        <ToggleGroup
          variant="outline"
          aria-label="Lọc theo trạng thái"
          value={[filter]}
          onValueChange={(value) => value[0] && setFilter(value[0] as Filter)}
        >
          {(Object.keys(filters) as Filter[]).map((key) => {
            const count = key === "all" ? null : columns.filter(filters[key].match).length
            return (
              <ToggleGroupItem key={key} value={key} disabled={count === 0 && filter !== key}>
                {filters[key].label}
                {count !== null && <span className="text-muted-foreground tabular-nums">{count}</span>}
              </ToggleGroupItem>
            )
          })}
        </ToggleGroup>
        <Button
          variant="ghost"
          className="ml-auto"
          disabled={visible.length === 0}
          onClick={() => setExpanded(allExpanded ? new Set() : new Set(visible.map((column) => column.column_name)))}
        >
          {allExpanded ? <ChevronsDownUpIcon data-icon="inline-start" /> : <ChevronsUpDownIcon data-icon="inline-start" />}
          {allExpanded ? "Thu gọn tất cả" : "Mở tất cả"}
        </Button>
      </div>
      <Table className="min-w-[1200px] table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className="w-56">Cột</TableHead>
            <TableHead className="w-32">Kiểu</TableHead>
            <TableHead className="w-24 text-center">Khóa chính</TableHead>
            <TableHead className="w-20 text-center">Duy nhất</TableHead>
            <TableHead className="w-16 text-center">PII</TableHead>
            <TableHead className="w-[20%]">Tên hiển thị</TableHead>
            <TableHead className="w-44">Vai trò</TableHead>
            <TableHead>Mô tả</TableHead>
          </TableRow>
        </TableHeader>
        {visible.map((column) => (
          <ColumnRow
            key={column.column_name}
            datasetId={datasetId}
            column={column}
            changes={changes[column.column_name] ?? {}}
            highlighted={highlighted.has(column.column_name)}
            error={errors[column.column_name] ?? null}
            open={expanded.has(column.column_name) || Boolean(errors[column.column_name])}
            onOpenChange={(open) => toggle(column.column_name, open)}
            onChange={onChange}
          />
        ))}
      </Table>
      {visible.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">Không có cột phù hợp.</p>}
    </div>
  )
}

type ColumnRowProps = {
  datasetId: number
  column: ColumnDictionary
  changes: Partial<ColumnFields>
  highlighted: boolean
  error: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onChange: ColumnChange
}

function ColumnRow({ datasetId, column, changes, highlighted, error, open, onOpenChange, onChange }: ColumnRowProps) {
  const fields = { ...columnFields(column), ...changes }
  const name = column.column_name
  const set = <Key extends keyof ColumnFields>(key: Key, value: ColumnFields[Key]) => onChange(name, key, value)
  const isMeasure = effectiveRole(column, fields) === "measure"
  const isKey = fields.is_primary_key ?? false
  const dirty = Object.keys(changes).length > 0
  const autoLabel = column.semantic_role_is_default ? `Tự suy · ${roleLabel(column.semantic_role)}` : "Tự suy"
  const roleItems = [{ value: AUTO, label: autoLabel }, ...semanticRoles]
  const cellClass = cn("align-top transition-colors duration-1000", highlighted && "bg-accent")

  return (
    <Collapsible
      open={open}
      onOpenChange={onOpenChange}
      render={<TableBody className="border-b last:border-b-0 [&_tr]:border-b-0" />}
    >
      <TableRow className="hover:bg-transparent has-aria-expanded:bg-transparent">
        <TableCell className={cellClass}>
          <div className="flex min-h-8 items-center gap-1">
            <CollapsibleTrigger
              render={<Button variant="ghost" size="icon-xs" aria-label={`Chi tiết cột ${name}`} />}
            >
              <ChevronRightIcon className={cn("transition-transform", open && "rotate-90")} />
            </CollapsibleTrigger>
            <div className="flex min-w-0 flex-wrap items-center gap-1">
              <span className="mr-0.5 flex min-w-0 items-center gap-1.5 font-medium">
                <span className="truncate" title={name}>
                  {name}
                </span>
                {dirty && <ChangedDot />}
              </span>
              {fields.referenced_column && (
                <Badge variant="outline">
                  <LinkIcon data-icon="inline-start" />
                  {fields.referenced_column.table_name}
                </Badge>
              )}
              {column.is_calculated && (
                <Tooltip>
                  <TooltipTrigger render={<Badge variant="outline" />}>Tính toán</TooltipTrigger>
                  <TooltipContent>Cột tính toán khai báo trong dataset Superset.</TooltipContent>
                </Tooltip>
              )}
              {!column.is_saved && !dirty && (
                <Tooltip>
                  <TooltipTrigger render={<Badge variant="outline" />}>Mặc định</TooltipTrigger>
                  <TooltipContent>Chưa lưu; đang hiển thị giá trị suy từ metadata.</TooltipContent>
                </Tooltip>
              )}
            </div>
          </div>
        </TableCell>
        <TableCell className={cellClass}>
          <span className="flex min-h-8 items-center font-mono text-xs text-muted-foreground">
            <span className="truncate" title={column.data_type}>
              {column.data_type}
            </span>
          </span>
        </TableCell>
        <TableCell className={cellClass}>
          <span className="flex min-h-8 items-center justify-center">
            <Checkbox
              aria-label={`${name} là khóa chính`}
              checked={isKey}
              onCheckedChange={(checked) => {
                // Unticking a column nobody had decided on returns it to "not decided", so the backend keeps
                // inferring keys from the name or a reference.
                set("is_primary_key", checked ? true : column.is_primary_key === null ? null : false)
                if (checked) set("is_unique", true)
              }}
            />
          </span>
        </TableCell>
        <TableCell className={cellClass}>
          <span className="flex min-h-8 items-center justify-center" title={isKey ? "Khóa chính luôn duy nhất" : undefined}>
            <Checkbox
              aria-label={`${name} có giá trị duy nhất`}
              checked={isKey || fields.is_unique}
              disabled={isKey}
              onCheckedChange={(checked) => set("is_unique", checked)}
            />
          </span>
        </TableCell>
        <TableCell className={cellClass}>
          <span className="flex min-h-8 items-center justify-center">
            <Checkbox
              aria-label={`${name} chứa dữ liệu cá nhân`}
              checked={fields.contains_pii}
              onCheckedChange={(checked) => set("contains_pii", checked)}
            />
          </span>
        </TableCell>
        <TableCell className={cellClass}>
          <Input
            aria-label={`Tên hiển thị của ${name}`}
            value={fields.display_name}
            maxLength={255}
            aria-invalid={!fields.display_name.trim() || undefined}
            className={cn(!column.is_saved && !changes.display_name && "text-muted-foreground")}
            onChange={(event) => set("display_name", event.target.value)}
          />
        </TableCell>
        <TableCell className={cellClass}>
          <Select
            items={roleItems}
            value={fields.semantic_role ?? AUTO}
            onValueChange={(value) => set("semantic_role", !value || value === AUTO ? null : (value as SemanticRole))}
          >
            <SelectTrigger aria-label={`Vai trò của ${name}`} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {roleItems.map((role) => (
                  <SelectItem key={role.value} value={role.value}>
                    {role.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </TableCell>
        <TableCell className={cellClass}>
          <Textarea
            aria-label={`Mô tả của ${name}`}
            rows={1}
            maxLength={2000}
            placeholder="Cột chứa gì, ý nghĩa giá trị"
            className="min-h-8 resize-none py-1.5"
            value={fields.description ?? ""}
            onChange={(event) => set("description", event.target.value || null)}
          />
        </TableCell>
      </TableRow>
      <CollapsibleContent render={<TableRow className="hover:bg-transparent has-aria-expanded:bg-transparent" />}>
        <TableCell colSpan={8} className="whitespace-normal pt-1 pb-4">
          <ColumnDetails datasetId={datasetId} column={column} fields={fields} isMeasure={isMeasure} error={error} set={set} />
        </TableCell>
      </CollapsibleContent>
    </Collapsible>
  )
}

type ColumnDetailsProps = {
  datasetId: number
  column: ColumnDictionary
  fields: ColumnFields
  isMeasure: boolean
  error: string | null
  set: <Key extends keyof ColumnFields>(key: Key, value: ColumnFields[Key]) => void
}

function ColumnDetails({ datasetId, column, fields, isMeasure, error, set }: ColumnDetailsProps) {
  // Superset column names may hold spaces, which an element id cannot.
  const id = `column-${column.column_name.replace(/\s+/g, "-")}`
  const temporalItems = [{ value: NONE, label: "Không phải thời gian" }, ...temporalKinds]

  return (
    <div className="grid items-start gap-x-4 gap-y-4 rounded-lg border bg-muted/30 p-4 md:grid-cols-2 xl:grid-cols-3">
      <Field>
        <FieldLabel htmlFor={`${id}-term`}>Thuật ngữ nghiệp vụ</FieldLabel>
        <Input
          id={`${id}-term`}
          placeholder="Khái niệm nghiệp vụ mà cột biểu diễn"
          value={fields.business_term ?? ""}
          onChange={(event) => set("business_term", event.target.value || null)}
        />
      </Field>
      <Field>
        <FieldLabel htmlFor={`${id}-unit`}>Đơn vị</FieldLabel>
        <Input
          id={`${id}-unit`}
          maxLength={128}
          placeholder="Ví dụ: °C, VND"
          value={fields.unit ?? ""}
          onChange={(event) => set("unit", event.target.value || null)}
        />
      </Field>
      <Field>
        <FieldLabel htmlFor={`${id}-format`}>Định dạng</FieldLabel>
        <Input
          id={`${id}-format`}
          maxLength={128}
          placeholder="Ví dụ: 0.0, dd/MM/yyyy"
          value={fields.format ?? ""}
          onChange={(event) => set("format", event.target.value || null)}
        />
      </Field>
      <Field>
        <FieldLabel htmlFor={`${id}-temporal`}>Kiểu thời gian</FieldLabel>
        <Select
          items={temporalItems}
          value={fields.temporal_kind ?? NONE}
          onValueChange={(value) => set("temporal_kind", !value || value === NONE ? null : (value as TemporalKind))}
        >
          <SelectTrigger id={`${id}-temporal`} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectGroup>
              {temporalItems.map((kind) => (
                <SelectItem key={kind.value} value={kind.value}>
                  {kind.label}
                </SelectItem>
              ))}
            </SelectGroup>
          </SelectContent>
        </Select>
      </Field>
      <Field>
        <FieldLabel htmlFor={`${id}-reference`}>Tham chiếu tới</FieldLabel>
        <ReferencePicker
          id={`${id}-reference`}
          datasetId={datasetId}
          columnName={column.column_name}
          value={fields.referenced_column}
          onChange={(value) => set("referenced_column", value)}
        />
      </Field>
      <Field>
        <FieldLabel>Từ đồng nghĩa</FieldLabel>
        <TagInput
          label={`Từ đồng nghĩa của ${column.column_name}`}
          placeholder="Từ người dùng hay gọi cột này, ngăn cách bằng dấu phẩy"
          max={20}
          value={fields.synonyms.map((synonym) => ({ id: synonym, value: synonym }))}
          onValueChange={(tags) => set("synonyms", tags.filter((tag) => !tag.error).map((tag) => tag.value))}
          validate={(value) => (value.length > 100 ? "Tối đa 100 ký tự." : null)}
        />
      </Field>
      <Field className="md:col-span-2 xl:col-span-3" data-disabled={!isMeasure || undefined}>
        <FieldLabel>
          Phép tổng hợp
          {!isMeasure && <span className="font-normal text-muted-foreground">· chỉ cho vai trò Số đo</span>}
        </FieldLabel>
        <ToggleGroup
          multiple
          variant="outline"
          size="sm"
          disabled={!isMeasure}
          value={fields.aggregations}
          onValueChange={(value) => set("aggregations", value as ColumnAggregation[])}
          className="flex-wrap"
        >
          {columnAggregations.map((aggregation) => (
            <ToggleGroupItem key={aggregation.value} value={aggregation.value}>
              {aggregation.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </Field>
      {error && <FieldError className="md:col-span-2 xl:col-span-3">{error}</FieldError>}
    </div>
  )
}
