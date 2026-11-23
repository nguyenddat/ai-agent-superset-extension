import { useState } from "react"
import { ChevronLeftIcon, ChevronsUpDownIcon, KeyRoundIcon, XIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Combobox, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from "@/components/ui/combobox"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Spinner } from "@/components/ui/spinner"

import { useDictionarySummary, useTableDictionary } from "./api"
import { DatasetCommand, DatasetIcon } from "./table-picker"
import type { ColumnDictionary, ReferencedColumn } from "./types"

type ReferencePickerProps = {
  id: string
  datasetId: number
  columnName: string
  value: ReferencedColumn | null
  onChange: (value: ReferencedColumn | null) => void
}

export function ReferencePicker({ id, datasetId, columnName, value, onChange }: ReferencePickerProps) {
  const [open, setOpen] = useState(false)
  const [targetId, setTargetId] = useState<number | null>(null)

  const choose = (next: ReferencedColumn | null) => {
    onChange(next)
    setOpen(false)
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (next) setTargetId(value?.dataset_id ?? null)
        setOpen(next)
      }}
    >
      <PopoverTrigger
        render={<Button id={id} variant="outline" className="w-full justify-between font-normal" />}
      >
        {value ? (
          <span className="truncate font-mono text-xs">
            {value.table_name}.{value.column_name}
          </span>
        ) : (
          <span className="text-muted-foreground">Không tham chiếu</span>
        )}
        <ChevronsUpDownIcon data-icon="inline-end" className="text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-96 max-w-[calc(100vw-2rem)] gap-0 p-0">
        {targetId !== null ? (
          <ColumnList
            datasetId={targetId}
            // A column cannot reference itself; other columns of the same dataset are fine.
            excluded={targetId === datasetId ? columnName : null}
            value={value}
            onBack={() => setTargetId(null)}
            onSelect={choose}
          />
        ) : (
          <TableList value={value} onSelect={setTargetId} onClear={() => choose(null)} />
        )}
      </PopoverContent>
    </Popover>
  )
}

function TableList({
  value,
  onSelect,
  onClear,
}: {
  value: ReferencedColumn | null
  onSelect: (datasetId: number) => void
  onClear: () => void
}) {
  const { data: summary } = useDictionarySummary()

  if (!summary) return <Spinner className="mx-auto my-4" />
  return (
    <DatasetCommand
      summary={summary}
      datasetId={value?.dataset_id ?? null}
      placeholder="Tìm bảng được tham chiếu..."
      empty="Không có bảng phù hợp."
      onSelect={onSelect}
      renderItem={(dataset) => (
        <>
          <DatasetIcon dataset={dataset} />
          <span className="flex min-w-0 flex-1 items-baseline justify-between gap-2">
            <span className="truncate">{dataset.display_name}</span>
            {dataset.display_name !== dataset.table_name && (
              <span className="truncate font-mono text-xs text-muted-foreground">{dataset.table_name}</span>
            )}
          </span>
        </>
      )}
    >
      {value && (
        <div className="p-1 pb-0">
          <Button variant="ghost" className="w-full justify-start font-normal" onClick={onClear}>
            <XIcon data-icon="inline-start" />
            Bỏ tham chiếu
          </Button>
        </div>
      )}
    </DatasetCommand>
  )
}

function ColumnList({
  datasetId,
  excluded,
  value,
  onBack,
  onSelect,
}: {
  datasetId: number
  excluded: string | null
  value: ReferencedColumn | null
  onBack: () => void
  onSelect: (value: ReferencedColumn) => void
}) {
  const { data: dictionary } = useTableDictionary(datasetId)
  const [query, setQuery] = useState("")
  const columns = dictionary?.columns.filter((column) => column.column_name !== excluded) ?? []
  const selected =
    value?.dataset_id === datasetId ? (columns.find((column) => column.column_name === value.column_name) ?? null) : null

  return (
    <>
      <div className="flex items-center gap-1 border-b p-1">
        <Button variant="ghost" size="icon-xs" aria-label="Chọn bảng khác" onClick={onBack}>
          <ChevronLeftIcon />
        </Button>
        <span className="truncate text-sm font-medium">{dictionary?.display_name ?? "..."}</span>
      </div>
      {dictionary ? (
        <Combobox
          inline
          open
          items={columns}
          value={selected}
          inputValue={query}
          onInputValueChange={setQuery}
          onValueChange={(column: ColumnDictionary | null) =>
            column &&
            onSelect({
              dataset_id: dictionary.dataset_id,
              schema_name: dictionary.schema_name,
              table_name: dictionary.table_name,
              column_name: column.column_name,
            })
          }
          itemToStringLabel={(column: ColumnDictionary) => `${column.column_name} ${column.display_name}`}
          isItemEqualToValue={(item: ColumnDictionary, current: ColumnDictionary) =>
            item.column_name === current.column_name
          }
        >
          <ComboboxInput showTrigger={false} placeholder="Tìm cột..." className="m-1 mb-0" autoFocus />
          <ComboboxEmpty className="flex">Không có cột phù hợp.</ComboboxEmpty>
          <ComboboxList className="max-h-80">
            {(column: ColumnDictionary) => (
              <ComboboxItem key={column.column_name} value={column}>
                {column.is_primary_key ? <KeyRoundIcon /> : <span className="size-4" />}
                <span className="flex min-w-0 flex-1 items-baseline gap-2">
                  <span className="truncate font-mono text-xs">{column.column_name}</span>
                  {column.display_name !== column.column_name && (
                    <span className="truncate text-muted-foreground">{column.display_name}</span>
                  )}
                </span>
                <span className="shrink-0 font-mono text-xs text-muted-foreground">{column.data_type}</span>
              </ComboboxItem>
            )}
          </ComboboxList>
        </Combobox>
      ) : (
        <Spinner className="mx-auto my-4" />
      )}
    </>
  )
}
