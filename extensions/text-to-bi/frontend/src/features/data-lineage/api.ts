import useSWR, { mutate } from "swr"

import { type ApiError, apiFetch } from "@/lib/api"

import { refreshModel } from "../business-model/api"
import type { LineageCanvasLayout, LineageGraph } from "../business-model/types"
import { dictionaryKey } from "../data-dictionary/api"
import type { TableDictionary } from "../data-dictionary/types"
import {
  columnId,
  type EdgeRef,
  type LineageColumn,
  type LineagePreview,
  type Transformation,
  type TransformationInput,
} from "./types"

const BASE = "/data-lineage"

// The extension scopes lineage by Superset database (?database_id=) where the standalone app scopes it by connection.
const scoped = (path: string, databaseId: number) => `${BASE}${path}?database_id=${databaseId}`
export const graphKey = (databaseId: number) => scoped("/graph", databaseId)
export const transformationsKey = (databaseId: number) => scoped("/transformations", databaseId)
const transformationPath = (databaseId: number, id: string) => scoped(`/transformations/${id}`, databaseId)

const fetcher = <T,>(path: string) => apiFetch<T>(path)

// Pass null while no database is selected yet: nothing is fetched.
export function useLineageGraph(databaseId: number | null) {
  return useSWR<LineageGraph, ApiError>(databaseId === null ? null : graphKey(databaseId), fetcher, {
    revalidateOnFocus: false,
  })
}

export function useTransformations(databaseId: number | null) {
  return useSWR<Transformation[], ApiError>(
    databaseId === null ? null : transformationsKey(databaseId),
    async (path: string) => (await apiFetch<{ transformations: Transformation[] }>(path)).transformations,
    { revalidateOnFocus: false },
  )
}

const toColumns = (dictionary: TableDictionary): LineageColumn[] =>
  dictionary.columns.map((column) => ({
    column_id: columnId(dictionary.dataset_id, column.column_name),
    table_id: dictionary.dataset_id,
    name: column.column_name,
    data_type: column.data_type,
    is_key: column.is_primary_key ?? false,
    display_name: column.display_name,
  }))

// Columns come from each dataset's dictionary; the requests share the cache with the dictionary tab.
async function fetchColumns(datasetIds: number[]) {
  const dictionaries = await Promise.all(
    datasetIds.map((datasetId) =>
      mutate<TableDictionary>(
        dictionaryKey(datasetId),
        (cached) => cached ?? apiFetch<TableDictionary>(dictionaryKey(datasetId)),
        { revalidate: false },
      ),
    ),
  )
  return new Map(datasetIds.map((datasetId, index) => [datasetId, toColumns(dictionaries[index]!)]))
}

export function useTableColumns(datasetIds: number[]) {
  const ids = [...new Set(datasetIds)].sort((a, b) => a - b)
  return useSWR<Map<number, LineageColumn[]>, ApiError>(
    ids.length ? ["lineage-columns", ...ids] : null,
    ([, ...keys]: [string, ...number[]]) => fetchColumns(keys),
    { revalidateOnFocus: false, keepPreviousData: true },
  )
}

// The business model embeds the same graph, so it reloads with it.
async function refresh(databaseId: number) {
  await Promise.all([mutate(graphKey(databaseId)), mutate(transformationsKey(databaseId)), refreshModel(databaseId)])
}

// Superset's edit right on the target and on every source dataset is required.
export async function saveTransformation(databaseId: number, input: TransformationInput, id?: string) {
  const { transformation } = await apiFetch<{ transformation: Transformation }>(
    id ? transformationPath(databaseId, id) : transformationsKey(databaseId),
    { method: id ? "PUT" : "POST", body: JSON.stringify(input) },
  )
  await refresh(databaseId)
  return transformation
}

export async function deleteTransformation(databaseId: number, id: string) {
  await apiFetch<{ message: string }>(transformationPath(databaseId, id), { method: "DELETE" })
  await refresh(databaseId)
}

export function previewSql(databaseId: number, targetDatasetId: number, sqlText: string) {
  return apiFetch<LineagePreview>(scoped("/preview", databaseId), {
    method: "POST",
    body: JSON.stringify({ target_dataset_id: targetDatasetId, sql_text: sqlText }),
  })
}

// Answers 400 when the dataset is not a view or materialized view of its database.
export function readViewSql(databaseId: number, datasetId: number) {
  return apiFetch<{ target_dataset_id: number; sql_text: string }>(
    scoped(`/datasets/${datasetId}/view-sql`, databaseId),
  )
}

// ---- Canvas and hand-drawn edges ----
// The standalone lineage page lays the graph out by itself and edits no edge; these serve the model canvas, which
// draws edges by hand (standalone's "Cạnh khai báo ở Mô hình").

// Admin only; keys come from nodeKey and edgeKey of business-model/types.
export async function saveLineageCanvas(databaseId: number, layout: LineageCanvasLayout) {
  await apiFetch<{ database_id: number }>(scoped("/canvas", databaseId), {
    method: "PUT",
    body: JSON.stringify(layout),
  })
  await mutate<LineageGraph>(graphKey(databaseId), (graph) => graph && { ...graph, canvas: layout }, {
    revalidate: false,
  })
  await refreshModel(databaseId)
}

// Superset's edit right on both datasets is required; they must belong to the same database.
export async function addEdge(databaseId: number, edge: EdgeRef) {
  await apiFetch<EdgeRef>(`${BASE}/edges`, { method: "POST", body: JSON.stringify(edge) })
  await refresh(databaseId)
}

// null goes back to the kind's own colour.
export async function setEdgeColor(databaseId: number, edge: EdgeRef, color: string | null) {
  await apiFetch<EdgeRef>(`${BASE}/edges/color`, { method: "PUT", body: JSON.stringify({ ...edge, color }) })
  await refresh(databaseId)
}

// An inferred edge (dictionary reference, saved transformation) is hidden rather than deleted.
export async function removeEdge(databaseId: number, edge: EdgeRef) {
  await apiFetch<EdgeRef>(`${BASE}/edges`, { method: "DELETE", body: JSON.stringify(edge) })
  await refresh(databaseId)
}
