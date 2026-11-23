import { useMemo, useState } from "react"
import { CheckIcon, Trash2Icon } from "lucide-react"

import { toast } from "@/components/toaster"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Combobox,
  ComboboxCollection,
  ComboboxEmpty,
  ComboboxGroup,
  ComboboxInput,
  ComboboxItem,
  ComboboxLabel,
  ComboboxList,
} from "@/components/ui/combobox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { ApiError } from "@/lib/api"

import { createDomain, deleteDomain, updateDomain } from "./api"
import type { BusinessDomain, ModelTable } from "./types"
import { DOMAIN_COLORS } from "./venn-layout"

type DomainDialogProps = {
  open: boolean
  domain: BusinessDomain | null
  tables: ModelTable[]
  usedColors: string[]
  onOpenChange: (open: boolean) => void
  onSaved: () => void
}

export function DomainDialog({ open, domain, onOpenChange, ...props }: DomainDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{domain ? "Sửa miền nghiệp vụ" : "Thêm miền nghiệp vụ"}</DialogTitle>
          <DialogDescription>
            Gom các bảng cùng phục vụ một nghiệp vụ. Một bảng có thể thuộc nhiều miền.
          </DialogDescription>
        </DialogHeader>
        {open ? (
          <DomainForm key={domain?.id ?? "new"} domain={domain} onClose={() => onOpenChange(false)} {...props} />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

type DomainFormProps = Omit<DomainDialogProps, "open" | "onOpenChange"> & { onClose: () => void }

type SchemaGroup = { value: string; items: ModelTable[] }

const NO_SCHEMA = "(không có schema)"

const searchText = (table: ModelTable) =>
  `${table.display_name} ${table.schema ? `${table.schema}.` : ""}${table.table_name} ${table.dataset_id}`

function DomainForm({ domain, tables, usedColors, onClose, onSaved }: DomainFormProps) {
  const [name, setName] = useState(domain?.name ?? "")
  const [description, setDescription] = useState(domain?.description ?? "")
  const [color, setColor] = useState(
    domain?.color ?? DOMAIN_COLORS.find((item) => !usedColors.includes(item)) ?? DOMAIN_COLORS[0],
  )
  const [selected, setSelected] = useState(() => new Set(domain?.dataset_ids ?? []))
  const [query, setQuery] = useState("")
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const schemas = useMemo<SchemaGroup[]>(() => {
    const groups = new Map<string, ModelTable[]>()
    for (const table of tables) {
      const schema = table.schema ?? NO_SCHEMA
      groups.set(schema, [...(groups.get(schema) ?? []), table])
    }
    return [...groups].map(([value, items]) => ({ value, items }))
  }, [tables])
  const chosen = useMemo(() => tables.filter((table) => selected.has(table.dataset_id)), [tables, selected])
  const nameTaken = error?.status === 409

  async function run(action: () => Promise<unknown>, message: string) {
    setBusy(true)
    setError(null)
    try {
      await action()
      toast.success(message)
      onSaved()
      onClose()
    } catch (e) {
      const apiError = e instanceof ApiError ? e : new ApiError(0, String(e))
      if (apiError.status === 409) setError(apiError)
      else toast.error(apiError.message)
    } finally {
      setBusy(false)
    }
  }

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    const input = {
      name: name.trim(),
      description: description.trim() || null,
      color,
      dataset_ids: [...selected],
    }
    const databaseTables = new Set(tables.map((table) => table.dataset_id))
    void run(
      () => (domain ? updateDomain(domain.id, input, databaseTables) : createDomain(input)),
      domain ? `Đã cập nhật miền "${input.name}".` : `Đã thêm miền "${input.name}".`,
    )
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-6">
      <FieldGroup>
        <Field data-invalid={nameTaken || undefined}>
          <FieldLabel htmlFor="domain-name">Tên miền</FieldLabel>
          <Input
            id="domain-name"
            value={name}
            maxLength={255}
            required
            autoFocus
            aria-invalid={nameTaken || undefined}
            placeholder="Ví dụ: Bán hàng"
            onChange={(event) => setName(event.target.value)}
          />
          {nameTaken ? <FieldError>{error.message}</FieldError> : null}
        </Field>
        <Field>
          <FieldLabel htmlFor="domain-description">Mô tả</FieldLabel>
          <Textarea
            id="domain-description"
            value={description}
            maxLength={2000}
            rows={2}
            placeholder="Nghiệp vụ này trả lời những câu hỏi gì?"
            onChange={(event) => setDescription(event.target.value)}
          />
        </Field>
        <Field>
          <FieldLabel>Màu</FieldLabel>
          <ToggleGroup
            value={[color]}
            onValueChange={(value) => value[0] && setColor(value[0] as string)}
            spacing={1}
            className="flex-wrap"
          >
            {DOMAIN_COLORS.map((item) => (
              <ToggleGroupItem key={item} value={item} aria-label={item} className="size-8 p-0">
                <span
                  className="flex size-5 items-center justify-center rounded-full text-white"
                  style={{ background: item }}
                >
                  {item === color ? <CheckIcon className="size-3" /> : null}
                </span>
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </Field>
        <Field>
          <div className="flex items-baseline justify-between">
            <FieldLabel>Bảng thuộc miền</FieldLabel>
            <span className="text-xs text-muted-foreground tabular-nums">Đã chọn {selected.size}</span>
          </div>
          {/* Standalone's cmdk Command list: an always-open Base UI combobox that toggles several datasets. */}
          <div className="overflow-hidden rounded-lg border">
            <Combobox
              inline
              open
              multiple
              items={schemas}
              value={chosen}
              inputValue={query}
              // Base UI empties the search after each pick in a multiple combobox; cmdk keeps it, so several tables
              // matching one query can be ticked in a row, as in standalone.
              onInputValueChange={(value, details) => details.reason !== "input-clear" && setQuery(value)}
              onValueChange={(value: ModelTable[]) => setSelected(new Set(value.map((table) => table.dataset_id)))}
              itemToStringLabel={searchText}
              isItemEqualToValue={(item: ModelTable, value: ModelTable) => item.dataset_id === value.dataset_id}
            >
              <ComboboxInput showTrigger={false} placeholder="Tìm theo tên bảng" className="m-1 mb-0" />
              <ComboboxEmpty className="flex py-6 empty:hidden">
                Không có bảng phù hợp.
              </ComboboxEmpty>
              <ComboboxList className="max-h-64">
                {(group: SchemaGroup) => (
                  <ComboboxGroup key={group.value} items={group.items}>
                    <ComboboxLabel>{group.value}</ComboboxLabel>
                    <ComboboxCollection>
                      {(table: ModelTable) => (
                        <ComboboxItem
                          key={table.dataset_id}
                          value={table}
                          // The checkbox shows the selection, as in standalone, so the item's own tick is hidden.
                          className="pr-1.5 [&>span[aria-hidden=true]:last-child]:hidden"
                        >
                          <Checkbox
                            checked={selected.has(table.dataset_id)}
                            tabIndex={-1}
                            className="pointer-events-none"
                          />
                          <span className="truncate">{table.display_name}</span>
                          {table.display_name !== table.table_name ? (
                            <span className="ml-auto truncate font-mono text-xs text-muted-foreground">
                              {table.table_name}
                            </span>
                          ) : null}
                        </ComboboxItem>
                      )}
                    </ComboboxCollection>
                  </ComboboxGroup>
                )}
              </ComboboxList>
            </Combobox>
          </div>
          <FieldDescription>Bảng chưa có từ điển sẽ được tạo từ điển mặc định khi lưu.</FieldDescription>
        </Field>
      </FieldGroup>

      <DialogFooter className="sm:justify-between">
        {domain ? (
          confirmDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Xóa miền? Bảng không bị xóa.</span>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                disabled={busy}
                onClick={() => void run(() => deleteDomain(domain.id), `Đã xóa miền "${domain.name}".`)}
              >
                Xóa
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
                Không
              </Button>
            </div>
          ) : (
            <Button type="button" variant="ghost" className="text-destructive" onClick={() => setConfirmDelete(true)}>
              <Trash2Icon data-icon="inline-start" />
              Xóa miền
            </Button>
          )
        ) : (
          <span />
        )}
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Hủy
          </Button>
          <Button type="submit" disabled={busy || !name.trim()}>
            {busy ? <Spinner data-icon="inline-start" /> : null}
            {domain ? "Lưu thay đổi" : "Thêm miền"}
          </Button>
        </div>
      </DialogFooter>
    </form>
  )
}
