import { useCallback, useState } from "react"
import { CircleXIcon, DatabaseIcon } from "lucide-react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Card, CardContent } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { navigate, pageHref, useSearchParams } from "@/lib/navigation"

import { useDictionarySummary } from "./api"
import { allDatasets } from "./dataset-groups"
import { DictionaryEditor } from "./dictionary-editor"
import { TablePicker } from "./table-picker"

export function DictionaryWorkspace() {
  const searchParams = useSearchParams()
  const { data: summary, error } = useDictionarySummary()
  const [dirty, setDirty] = useState(false)
  const [pendingDatasetId, setPendingDatasetId] = useState<number | null>(null)

  const datasets = summary ? allDatasets(summary) : []
  const requested = Number(searchParams.get("dataset"))
  const current = datasets.find((dataset) => dataset.dataset_id === requested) ?? datasets[0]

  const openDataset = useCallback((nextDatasetId: number) => {
    setDirty(false)
    navigate(pageHref({ section: "dictionary", dataset: nextDatasetId }), { replace: true, force: true })
  }, [])
  const selectDataset = (nextDatasetId: number) => {
    if (nextDatasetId === current?.dataset_id) return
    if (dirty) setPendingDatasetId(nextDatasetId)
    else openDataset(nextDatasetId)
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <CircleXIcon />
        <AlertDescription>{error.message}</AlertDescription>
      </Alert>
    )
  }

  if (!summary) {
    return (
      <Card size="sm">
        <CardContent className="flex flex-col gap-3">
          <Skeleton className="h-8 w-64" />
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="h-12" />
          ))}
        </CardContent>
      </Card>
    )
  }

  if (!current) {
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <DatabaseIcon />
          </EmptyMedia>
          <EmptyTitle>Chưa có dataset để mô tả</EmptyTitle>
          <EmptyDescription>
            Tạo dataset trong Superset, hoặc nhờ quản trị viên cấp quyền đọc dataset, để bắt đầu mô tả.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <>
      <DictionaryEditor
        key={current.dataset_id}
        datasetId={current.dataset_id}
        picker={(label) => (
          <TablePicker summary={summary} datasetId={current.dataset_id} label={label} onSelect={selectDataset} />
        )}
        fallbackLabel={current.display_name}
        catalogTables={datasets.filter((dataset) => dataset.layout === "indicator_catalog")}
        onDirtyChange={setDirty}
      />

      <AlertDialog open={pendingDatasetId !== null} onOpenChange={(open) => !open && setPendingDatasetId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Bỏ thay đổi chưa lưu?</AlertDialogTitle>
            <AlertDialogDescription>
              Bảng hiện tại còn thay đổi chưa lưu. Chuyển sang bảng khác sẽ bỏ các thay đổi đó.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Ở lại</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (pendingDatasetId !== null) openDataset(pendingDatasetId)
                setPendingDatasetId(null)
              }}
            >
              Bỏ thay đổi
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
