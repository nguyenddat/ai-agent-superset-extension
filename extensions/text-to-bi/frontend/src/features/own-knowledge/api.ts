import useSWR, { mutate } from "swr"

import { type ApiError, apiFetch } from "@/lib/api"

import { refreshGlossary } from "../glossary-management/api"
import { metricsKey } from "../metric-management/api"
import { refreshRules } from "../expert-rule-management/api"
import type { KnowledgeKind, OwnEntry, ReviewAction } from "./types"

// The admin routes are require_admin on the Superset session, so there is no review password as in standalone. One
// list holds every entry the admin may read; screens keep the datasets of their database.
const BASE = "/own-knowledge/admin/entries"
export const entriesKey = BASE

const refreshEntries = () => mutate(entriesKey)

// Pass false to skip the request, e.g. for a user who is not an admin and would get 403.
export function useOwnEntries(enabled = true) {
  return useSWR<OwnEntry[], ApiError>(
    enabled ? entriesKey : null,
    async (path: string) => (await apiFetch<{ entries: OwnEntry[] }>(path)).entries,
    { revalidateOnFocus: false },
  )
}

const post = <T,>(path: string, body: unknown) => apiFetch<T>(path, { method: "POST", body: JSON.stringify(body) })

export async function reviewEntry(entry: OwnEntry, action: ReviewAction, note: string | null) {
  const { entry: saved } = await post<{ entry: OwnEntry }>(`${BASE}/${entry.id}/review`, {
    expected_version: entry.version,
    action,
    note,
  })
  await refreshEntries()
  return saved
}

// The metric and rule overview cards keep their own keys over several datasets.
const refreshMetrics = (datasetId: number) =>
  Promise.all([
    mutate(metricsKey(datasetId)),
    mutate((key) => Array.isArray(key) && key[0] === "metrics-all"),
  ])
const refreshAllRules = (datasetId: number) =>
  Promise.all([
    refreshRules(datasetId),
    mutate((key) => Array.isArray(key) && key[0] === "/expert-rules/datasets" && key[1] === "all"),
  ])

export async function promoteEntry<T>(
  entry: OwnEntry,
  kind: KnowledgeKind,
  payload: Record<string, unknown>,
  note: string | null,
) {
  // The server takes the dataset from the entry, so the form's copy is left out.
  const body = { ...payload }
  delete body.dataset_id
  const { result } = await post<{ result: { entry: OwnEntry; target: T } }>(`${BASE}/${entry.id}/promote`, {
    expected_version: entry.version,
    target_kind: kind,
    payload: body,
    note,
  })
  await Promise.all([
    refreshEntries(),
    kind === "glossary"
      ? refreshGlossary(entry.dataset_id)
      : kind === "metric"
        ? refreshMetrics(entry.dataset_id)
        : refreshAllRules(entry.dataset_id),
  ])
  return result.target
}
