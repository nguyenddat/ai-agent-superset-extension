import useSWR, { mutate } from "swr"

import { type ApiError, apiFetch } from "@/lib/api"

import { domainsKey, fetchDomains } from "./domains"
import type { BusinessDomain, BusinessModel, DataLayer, DomainInput, LayerInput } from "./types"

const BASE = "/business-model"

// The extension scopes a model by Superset database where the standalone app scopes it by connection.
export const modelKey = (databaseId: number) => `${BASE}/databases/${databaseId}`
export const layersKey = `${BASE}/layers/`

const fetcher = <T,>(path: string) => apiFetch<T>(path)

// Pass null while no database is selected yet: nothing is fetched.
export function useBusinessModel(databaseId: number | null) {
  return useSWR<BusinessModel, ApiError>(databaseId === null ? null : modelKey(databaseId), fetcher, {
    revalidateOnFocus: false,
  })
}

export function updateModel(databaseId: number, change: (model: BusinessModel) => BusinessModel) {
  return mutate<BusinessModel>(modelKey(databaseId), (model) => model && change(model), { revalidate: false })
}

export const refreshModel = (databaseId: number) => mutate(modelKey(databaseId))

// Layers and domains are shared by every database, so a write reloads every model in the cache.
const refreshModels = () =>
  mutate((key) => typeof key === "string" && key.startsWith(`${BASE}/databases/`) && !key.endsWith("/canvas"))

// ---- Layers ----

export function useDataLayers() {
  return useSWR<DataLayer[], ApiError>(
    layersKey,
    async (path: string) => (await apiFetch<{ layers: DataLayer[] }>(path)).layers,
    { revalidateOnFocus: false },
  )
}

async function afterLayerWrite<T>(result: T) {
  await Promise.all([mutate(layersKey), refreshModels()])
  return result
}

export async function createLayer(input: LayerInput) {
  const { layer } = await apiFetch<{ layer: DataLayer }>(layersKey, { method: "POST", body: JSON.stringify(input) })
  return afterLayerWrite(layer)
}

export async function updateLayer(layerId: string, input: LayerInput) {
  const { layer } = await apiFetch<{ layer: DataLayer }>(`${BASE}/layers/${layerId}`, {
    method: "PUT",
    body: JSON.stringify(input),
  })
  return afterLayerWrite(layer)
}

export async function deleteLayer(layerId: string) {
  await apiFetch<{ message: string }>(`${BASE}/layers/${layerId}`, { method: "DELETE" })
  await afterLayerWrite(undefined)
}

// One array per level, top to bottom, each listing every layer of that level in order; together they must name every
// layer exactly once.
export async function reorderLayers(levels: string[][]) {
  const { layers } = await apiFetch<{ layers: DataLayer[] }>(`${BASE}/layers/order`, {
    method: "PUT",
    body: JSON.stringify({ levels }),
  })
  return afterLayerWrite(layers)
}

// Superset's edit right on the dataset is required; null takes the dataset out of every layer.
export async function assignLayer(datasetId: number, layerId: string | null) {
  const { assignment } = await apiFetch<{ assignment: { dataset_id: number; layer_id: string | null } }>(
    `${BASE}/datasets/${datasetId}/layer`,
    { method: "PUT", body: JSON.stringify({ layer_id: layerId }) },
  )
  return assignment
}

// ---- Domains ----
// Callers refresh the model themselves, as in the standalone app; the shared domain list that metrics, glossary
// terms and expert rules read (useBusinessDomains) is refreshed here.

// Domains span every database while the model lists only this database's datasets, so a write keeps the members
// that belong to other databases.
async function withOtherMembers(domainId: string, datasetIds: number[], databaseDatasetIds: Set<number>) {
  const domains = await fetchDomains()
  const others = domains
    .find((domain) => domain.id === domainId)
    ?.dataset_ids.filter((id) => !databaseDatasetIds.has(id))
  return [...new Set([...(others ?? []), ...datasetIds])]
}

export async function createDomain(input: DomainInput) {
  const { domain } = await apiFetch<{ domain: BusinessDomain }>(`${BASE}/domains/`, {
    method: "POST",
    body: JSON.stringify(input),
  })
  await mutate(domainsKey)
  return domain
}

export async function updateDomain(domainId: string, input: DomainInput, databaseDatasetIds: Set<number>) {
  const dataset_ids = await withOtherMembers(domainId, input.dataset_ids, databaseDatasetIds)
  const { domain } = await apiFetch<{ domain: BusinessDomain }>(`${BASE}/domains/${domainId}`, {
    method: "PUT",
    body: JSON.stringify({ ...input, dataset_ids }),
  })
  await mutate(domainsKey)
  return domain
}

export async function deleteDomain(domainId: string) {
  await apiFetch<{ message: string }>(`${BASE}/domains/${domainId}`, { method: "DELETE" })
  await mutate(domainsKey)
}

// ---- Canvas ----

// Admin only. The layout is free-form JSON up to 1 MB; the saved value comes back as model.business_canvas.
export async function saveBusinessCanvas(databaseId: number, layout: Record<string, unknown>) {
  const { canvas } = await apiFetch<{ canvas: { database_id: number; layout: Record<string, unknown> } }>(
    `${modelKey(databaseId)}/canvas`,
    { method: "PUT", body: JSON.stringify({ layout }) },
  )
  await updateModel(databaseId, (model) => ({ ...model, business_canvas: canvas.layout }))
  return canvas.layout
}
