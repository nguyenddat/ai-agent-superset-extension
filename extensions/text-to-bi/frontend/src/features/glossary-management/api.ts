import useSWR, { mutate } from "swr"

import { type ApiError, apiFetch } from "@/lib/api"

import type {
  DatasetMetric,
  GlossaryContent,
  GlossaryCreate,
  GlossaryTerm,
  GlossaryUpdate,
} from "./types"

const BASE = "/glossary"
export const glossaryKey = (datasetId: number) => `${BASE}/datasets/${datasetId}`

// Every answer is wrapped (`{terms}`, `{term}`, ...); the hooks hand back what is inside.
const fetchTerms = (datasetId: number) =>
  apiFetch<{ terms: GlossaryTerm[] }>(glossaryKey(datasetId)).then((body) => body.terms)

export function useGlossary(datasetId: number | null) {
  return useSWR<GlossaryTerm[], ApiError>(
    datasetId === null ? null : glossaryKey(datasetId),
    () => fetchTerms(datasetId!),
    { revalidateOnFocus: false },
  )
}

const ALL_TAG = "glossary-all"

// The overview card keeps its own entry over every dataset, so a write refreshes it too.
export async function refreshGlossary(datasetId: number) {
  await mutate(glossaryKey(datasetId))
  await mutate((key) => Array.isArray(key) && key[0] === ALL_TAG)
}

async function write(datasetId: number, path: string, method: string, body?: unknown) {
  const saved = await apiFetch<{ term: GlossaryTerm }>(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  await refreshGlossary(datasetId)
  return saved.term
}

export function createTerm(input: GlossaryCreate) {
  return write(input.dataset_id, `${BASE}/`, "POST", input)
}

// The extension saves a draft with PUT on the term itself (standalone: PUT /<id>/draft).
export function saveDraft(datasetId: number, id: string, input: GlossaryUpdate) {
  return write(datasetId, `${BASE}/${id}`, "PUT", input)
}

export function approveTerm(datasetId: number, id: string, expectedRevision: number) {
  return write(datasetId, `${BASE}/${id}/approve`, "POST", { expected_revision: expectedRevision })
}

export function revokeTerm(datasetId: number, id: string, expectedRevision: number) {
  return write(datasetId, `${BASE}/${id}/revoke`, "POST", { expected_revision: expectedRevision })
}

// Approval is all or nothing, so keeping only part of a draft saves that part as a newer draft and approves it.
export async function approveContent(datasetId: number, term: GlossaryTerm, content: GlossaryContent) {
  const draft = await apiFetch<{ term: GlossaryTerm }>(`${BASE}/${term.id}`, {
    method: "PUT",
    body: JSON.stringify({
      ...content,
      business_domain_ids: term.business_domains.map((domain) => domain.id),
      expected_revision: term.current.number,
    }),
  })
  return approveTerm(datasetId, term.id, draft.term.current.number)
}

export async function deleteTerm(datasetId: number, id: string) {
  await apiFetch<unknown>(`${BASE}/${id}`, { method: "DELETE" })
  await refreshGlossary(datasetId)
}

// Metrics a link may name. The key is our own: the metric section may cache the same URL in another shape.
export function useDatasetMetrics(datasetId: number | null) {
  return useSWR<DatasetMetric[], ApiError>(
    datasetId === null ? null : ["glossary-metrics", datasetId],
    ([, id]: [string, number]) =>
      apiFetch<{ metrics: DatasetMetric[] }>(`/metrics/datasets/${id}`).then((body) => body.metrics),
    { revalidateOnFocus: false },
  )
}

// The overview counts terms across every dataset the user may read, as standalone counts a whole connection. Each
// request shares the cache with the glossary section.
async function fetchAllTerms(datasetIds: number[]) {
  const lists = await Promise.all(
    datasetIds.map((datasetId) =>
      mutate<GlossaryTerm[]>(glossaryKey(datasetId), (cached) => cached ?? fetchTerms(datasetId), {
        revalidate: false,
      }),
    ),
  )
  return lists.map((terms, index) => ({ datasetId: datasetIds[index], terms: terms ?? [] }))
}

export function useAllGlossaries(datasetIds: number[] | null) {
  const ids = datasetIds ? [...new Set(datasetIds)].sort((a, b) => a - b) : null
  return useSWR(ids ? [ALL_TAG, ...ids] : null, ([, ...keys]: [string, ...number[]]) => fetchAllTerms(keys), {
    revalidateOnFocus: false,
    keepPreviousData: true,
  })
}
