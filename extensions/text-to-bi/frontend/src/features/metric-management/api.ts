import useSWR, { mutate } from "swr"

import { type ApiError, apiFetch } from "@/lib/api"

import type { Metric, MetricInput, MetricPatch } from "./types"

const BASE = "/metrics"
export const metricsKey = (datasetId: number) => `${BASE}/datasets/${datasetId}`
// The overview card reads every dataset's metrics under one key.
export const allMetricsKey = (datasetIds: number[]) => ["metrics-all", ...datasetIds] as const

const listFetcher = async (path: string) => (await apiFetch<{ metrics: Metric[] }>(path)).metrics

export function useMetrics(datasetId: number | null) {
  return useSWR<Metric[], ApiError>(datasetId === null ? null : metricsKey(datasetId), listFetcher, {
    revalidateOnFocus: false,
  })
}

// No backend endpoint counts metrics across datasets, so the overview asks each readable dataset in turn.
export function useAllMetrics(datasetIds: number[] | undefined) {
  return useSWR<Map<number, Metric[]>, ApiError>(
    datasetIds ? allMetricsKey(datasetIds) : null,
    async () => {
      const lists = await Promise.all(
        datasetIds!.map((id) => listFetcher(metricsKey(id)).catch(() => [] as Metric[])),
      )
      return new Map(datasetIds!.map((id, index) => [id, lists[index]!]))
    },
    { revalidateOnFocus: false },
  )
}

// A write changes one dataset's list and the overview counts.
async function refresh(datasetId: number) {
  await mutate(metricsKey(datasetId))
  await mutate((key) => Array.isArray(key) && key[0] === "metrics-all")
}

const one = async (path: string, init: RequestInit) => (await apiFetch<{ metric: Metric }>(path, init)).metric

export async function createMetric(input: MetricInput) {
  const saved = await one(`${BASE}/`, { method: "POST", body: JSON.stringify(input) })
  await refresh(input.dataset_id)
  return saved
}

export async function updateMetric(datasetId: number, id: string, changes: MetricPatch) {
  const saved = await one(`${BASE}/${id}`, { method: "PATCH", body: JSON.stringify(changes) })
  await refresh(datasetId)
  return saved
}

export async function deleteMetric(datasetId: number, id: string) {
  await apiFetch<void>(`${BASE}/${id}`, { method: "DELETE" })
  await refresh(datasetId)
}

export async function approveMetric(datasetId: number, id: string) {
  const saved = await one(`${BASE}/${id}/approve`, { method: "POST" })
  await refresh(datasetId)
  return saved
}

export async function revokeMetric(datasetId: number, id: string) {
  const saved = await one(`${BASE}/${id}/revoke`, { method: "POST" })
  await refresh(datasetId)
  return saved
}
