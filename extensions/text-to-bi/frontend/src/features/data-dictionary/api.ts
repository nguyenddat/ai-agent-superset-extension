import useSWR, { mutate } from "swr"

import { ApiError, apiFetch, csrfToken, errorFrom, EXTENSION_API } from "@/lib/api"
import { readServerSentEvents } from "@/lib/sse"

import type { AutofillEvent, DictionaryStats, DictionarySummary, TableDictionary } from "./types"

const fetcher = <T,>(path: string) => apiFetch<T>(path)

// One dictionary covers every dataset the user may read, so the summary and stats keys take no scope.
export const summaryKey = "/data-dictionary/summary"
export const STATS_LIMIT = 8
export const statsKey = `/data-dictionary/stats?limit=${STATS_LIMIT}`
export const dictionaryKey = (datasetId: number) => `/data-dictionary/datasets/${datasetId}`

export function useDictionarySummary() {
  return useSWR<DictionarySummary, ApiError>(summaryKey, fetcher)
}

export function useDictionaryStats() {
  return useSWR<DictionaryStats, ApiError>(statsKey, fetcher)
}

export function useTableDictionary(datasetId: number | null) {
  return useSWR<TableDictionary, ApiError>(datasetId === null ? null : dictionaryKey(datasetId), fetcher, {
    revalidateOnFocus: false,
  })
}

export async function refreshOverview() {
  await mutate(summaryKey)
  await mutate(statsKey)
}

async function storeDictionary(dictionary: TableDictionary) {
  await mutate(dictionaryKey(dictionary.dataset_id), dictionary, { revalidate: false })
  await refreshOverview()
}

export async function saveTableDictionary(datasetId: number, body: unknown) {
  const dictionary = await apiFetch<TableDictionary>(dictionaryKey(datasetId), {
    method: "PUT",
    body: JSON.stringify(body),
  })
  await storeDictionary(dictionary)
  return dictionary
}

export async function saveColumnDictionaries(datasetId: number, columns: unknown[]) {
  const dictionary = await apiFetch<TableDictionary>(`${dictionaryKey(datasetId)}/columns`, {
    method: "PUT",
    body: JSON.stringify({ columns }),
  })
  await storeDictionary(dictionary)
  return dictionary
}

export async function* streamAutofill(datasetId: number, signal: AbortSignal): AsyncGenerator<AutofillEvent> {
  let response: Response
  try {
    response = await fetch(`${EXTENSION_API}${dictionaryKey(datasetId)}/autofill`, {
      method: "POST",
      credentials: "same-origin",
      signal,
      headers: { Accept: "text/event-stream", "X-CSRFToken": await csrfToken() },
    })
  } catch (error) {
    if (signal.aborted || error instanceof ApiError) throw error
    throw new ApiError(0, "Không kết nối được tới Superset.")
  }
  if (!response.ok) throw await errorFrom(response, "Không thể bắt đầu tự động điền.")
  for await (const message of readServerSentEvents(response)) {
    yield { event: message.event, data: JSON.parse(message.data) } as AutofillEvent
  }
}
