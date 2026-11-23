import { useMemo, useState } from "react"
import { ChevronsUpDownIcon, CodeIcon, TableIcon } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

import { allDatasets, type DatasetGroup, type DatasetOption, datasetGroups, datasetSearchText } from "./dataset-groups"
import type { DictionarySummary } from "./types"

export function DatasetIcon({ dataset }: { dataset: { dataset_kind: string } }) {
  return dataset.dataset_kind === "virtual" ? <CodeIcon /> : <TableIcon />
}

// A searchable list of every dataset inside a popover, as the standalone app does with Command: the Combobox is
// inline, so the popover owns opening and closing.
export function DatasetCommand({
  summary,
  datasetId,
  placeholder,
  empty,
  onSelect,
  renderItem,
  children,
}: {
  summary: DictionarySummary
  datasetId: number | null
  placeholder: string
  empty: React.ReactNode
  onSelect: (datasetId: number) => void
  renderItem: (dataset: DatasetOption) => React.ReactNode
  children?: React.ReactNode
}) {
  const groups = useMemo(() => datasetGroups(summary), [summary])
  const selected = useMemo(
    () => allDatasets(summary).find((dataset) => dataset.dataset_id === datasetId) ?? null,
    [summary, datasetId],
  )
  // Held here so the search box starts empty instead of showing the selected dataset's label.
  const [query, setQuery] = useState("")

  return (
    <Combobox
      inline
      open
      items={groups}
      value={selected}
      inputValue={query}
      onInputValueChange={setQuery}
      onValueChange={(value: DatasetOption | null) => value && onSelect(value.dataset_id)}
      itemToStringLabel={(dataset: DatasetOption) => datasetSearchText(dataset)}
      isItemEqualToValue={(item: DatasetOption, value: DatasetOption) => item.dataset_id === value.dataset_id}
    >
      <ComboboxInput showTrigger={false} placeholder={placeholder} className="m-1 mb-0" autoFocus />
      {children}
      <ComboboxEmpty className="flex empty:hidden">{empty}</ComboboxEmpty>
      <ComboboxList className="max-h-96">
        {(group: DatasetGroup) => (
          <ComboboxGroup key={group.value} items={group.items}>
            <ComboboxLabel>{group.value}</ComboboxLabel>
            <ComboboxCollection>
              {(dataset: DatasetOption) => (
                <ComboboxItem key={dataset.dataset_id} value={dataset}>
                  {renderItem(dataset)}
                </ComboboxItem>
              )}
            </ComboboxCollection>
          </ComboboxGroup>
        )}
      </ComboboxList>
    </Combobox>
  )
}

export function TablePicker({
  summary,
  datasetId,
  label,
  onSelect,
}: {
  summary: DictionarySummary
  datasetId: number
  label: string
  onSelect: (datasetId: number) => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            aria-label="Chọn bảng"
            className="-ml-2 h-auto max-w-full min-w-0 px-2 py-1 text-base font-semibold"
          />
        }
      >
        <span className="truncate">{label}</span>
        <ChevronsUpDownIcon data-icon="inline-end" className="text-muted-foreground" />
      </PopoverTrigger>
      <PopoverContent align="start" className="w-96 max-w-[calc(100vw-2rem)] gap-0 p-0">
        <DatasetCommand
          summary={summary}
          datasetId={datasetId}
          placeholder="Tìm bảng..."
          empty="Không có bảng phù hợp."
          onSelect={(next) => {
            setOpen(false)
            onSelect(next)
          }}
          renderItem={(dataset) => (
            <>
              <DatasetIcon dataset={dataset} />
              <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate">{dataset.display_name}</span>
                {dataset.display_name !== dataset.table_name && (
                  <span className="truncate font-mono text-xs text-muted-foreground">{dataset.table_name}</span>
                )}
              </div>
              <Badge variant={dataset.is_saved ? "secondary" : "outline"} className="tabular-nums">
                {dataset.described_column_count}/{dataset.column_count}
              </Badge>
            </>
          )}
        />
        <p className="border-t px-3 py-2 text-xs text-muted-foreground">
          {summary.described_table_count}/{summary.table_count} bảng đã mô tả · số trên mỗi bảng: cột đã mô tả / tổng
          số cột
        </p>
      </PopoverContent>
    </Popover>
  )
}
