import { useCallback, useEffect, useRef, useState } from "react"
import { mutate } from "swr"

import { toast } from "@/components/toaster"

import { dictionaryKey, refreshOverview, streamAutofill } from "./api"
import type { TableDictionary } from "./types"

export type AutofillState = {
  status: "idle" | "running" | "done" | "error"
  phase: number
  processed: number
  total: number
  failed: number
  startedAt?: number
  error?: string
}

const idle: AutofillState = { status: "idle", phase: 0, processed: 0, total: 0, failed: 0 }
const HIGHLIGHT_MS = 1600

export function useAutofill(dictionary: TableDictionary) {
  const [state, setState] = useState<AutofillState>(idle)
  const [highlighted, setHighlighted] = useState<{ columns: Set<string>; table: boolean }>({
    columns: new Set(),
    table: false,
  })
  const controller = useRef<AbortController | null>(null)
  const timers = useRef<number[]>([])
  const datasetId = dictionary.dataset_id

  const highlight = useCallback((columns: string[], table = false) => {
    setHighlighted((current) => ({
      columns: new Set([...current.columns, ...columns]),
      table: current.table || table,
    }))
    timers.current.push(
      window.setTimeout(() => {
        setHighlighted((current) => ({
          columns: new Set([...current.columns].filter((name) => !columns.includes(name))),
          table: table ? false : current.table,
        }))
      }, HIGHLIGHT_MS),
    )
  }, [])

  useEffect(
    () => () => {
      controller.current?.abort()
      timers.current.forEach((timer) => window.clearTimeout(timer))
    },
    [],
  )

  const start = useCallback(async () => {
    controller.current?.abort()
    const abort = new AbortController()
    controller.current = abort
    setState({ ...idle, status: "running", startedAt: Date.now() })
    try {
      for await (const message of streamAutofill(datasetId, abort.signal)) {
        if (message.event === "status") {
          const { processed, total } = message.data
          setState((current) => ({ ...current, processed, total, phase: processed > 0 ? 1 : 0 }))
        } else if (message.event === "columns") {
          const filled = new Map(message.data.columns.map((column) => [column.column_name, column]))
          await mutate<TableDictionary>(
            dictionaryKey(datasetId),
            (current) =>
              current && {
                ...current,
                columns: current.columns.map((column) => filled.get(column.column_name) ?? column),
              },
            { revalidate: false },
          )
          highlight([...filled.keys()])
          setState((current) => ({ ...current, processed: message.data.processed, total: message.data.total }))
        } else if (message.event === "table") {
          await mutate(dictionaryKey(datasetId), message.data, { revalidate: false })
          highlight([], true)
        } else if (message.event === "done") {
          const { failed_columns: failed, table_filled: tableFilled } = message.data
          setState((current) => ({ ...current, status: "done", phase: 1, failed }))
          if (failed || !tableFilled) {
            const missing = [failed ? `${failed} cột` : null, tableFilled ? null : "mô tả bảng"].filter(Boolean)
            toast.warning(`Đã tự động điền; chưa có gợi ý cho ${missing.join(" và ")}.`)
          } else {
            toast.success("Đã tự động điền từ điển.")
          }
        } else if (message.event === "error") {
          setState((current) => ({ ...current, status: "error", error: message.data.message }))
        }
      }
    } catch (error) {
      setState(idle)
      if (abort.signal.aborted) toast.info("Đã dừng tự động điền; các cột đã nhận gợi ý vẫn được lưu.")
      else toast.error(error instanceof Error ? error.message : "Không thể tự động điền.")
    } finally {
      if (controller.current === abort) controller.current = null
      await refreshOverview()
    }
  }, [datasetId, highlight])

  const cancel = useCallback(() => controller.current?.abort(), [])
  const dismiss = useCallback(() => setState(idle), [])

  return { state, highlighted, start, cancel, dismiss }
}
