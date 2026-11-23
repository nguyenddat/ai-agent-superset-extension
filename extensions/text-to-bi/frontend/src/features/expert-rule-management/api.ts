import useSWR, { mutate } from "swr"

import { type ApiError, apiFetch } from "@/lib/api"

import type {
  DiscoveryTerm,
  ExpertRule,
  RuleContent,
  RuleCreate,
  RuleMetric,
  RuleOptions,
  RuleRevision,
  RuleTerm,
  RuleUpdate,
} from "./types"

const BASE = "/expert-rules"
export const rulesKey = (datasetId: number) => `${BASE}/datasets/${datasetId}`
const optionsKey = (datasetId: number) => `${BASE}/datasets/${datasetId}/options`
const revisionsKey = (ruleId: string) => `${BASE}/${ruleId}/revisions`
// The glossary and metric lists are read in this module's own shape, so their keys carry a tag: the sibling
// features may cache the same paths unwrapped.
const termsKey = (datasetId: number) => [`/glossary/datasets/${datasetId}`, "expert-rules"] as const
const eligibleTermsKey = (datasetId: number) => [`/glossary/datasets/${datasetId}/discovery`, "expert-rules"] as const
const metricsKey = (datasetId: number) => [`/metrics/datasets/${datasetId}`, "expert-rules"] as const

// The extension answers `{rules: [...]}`, `{rule: {...}}`…; these unwrap the one field each endpoint returns.
const field =
  <T,>(name: string) =>
  async (key: string | readonly [string, ...unknown[]]) => {
    const path = typeof key === "string" ? key : key[0]
    return (await apiFetch<Record<string, T>>(path))[name]
  }

export function useRules(datasetId: number | null) {
  return useSWR<ExpertRule[], ApiError>(datasetId === null ? null : rulesKey(datasetId), field<ExpertRule[]>("rules"), {
    revalidateOnFocus: false,
  })
}

// Which glossary terms a rule may use depends on what is approved right now, so the options follow focus.
export function useRuleOptions(datasetId: number) {
  return useSWR<RuleOptions, ApiError>(optionsKey(datasetId), field<RuleOptions>("options"))
}

export function useEligibleTerms(datasetId: number) {
  return useSWR<DiscoveryTerm[], ApiError>(eligibleTermsKey(datasetId), field<DiscoveryTerm[]>("terms"))
}

export function useRuleTerms(datasetId: number) {
  return useSWR<RuleTerm[], ApiError>(termsKey(datasetId), field<RuleTerm[]>("terms"), { revalidateOnFocus: false })
}

export function useRuleMetrics(datasetId: number) {
  return useSWR<RuleMetric[], ApiError>(metricsKey(datasetId), field<RuleMetric[]>("metrics"), {
    revalidateOnFocus: false,
  })
}

export function useRuleRevisions(ruleId: string | null, revision: number) {
  return useSWR<RuleRevision[], ApiError>(
    ruleId && [revisionsKey(ruleId), revision],
    field<RuleRevision[]>("revisions"),
    { revalidateOnFocus: false },
  )
}

// Rules of several datasets at once, for the overview card; the summary lists the datasets the user may read.
export function useRulesOfDatasets(datasetIds: number[] | null) {
  return useSWR<Map<number, ExpertRule[]>, ApiError>(
    datasetIds && [`${BASE}/datasets`, "all", ...datasetIds],
    async () => {
      const lists = await Promise.all(
        datasetIds!.map(async (id) => [id, await field<ExpertRule[]>("rules")(rulesKey(id))] as const),
      )
      return new Map(lists)
    },
    { revalidateOnFocus: false },
  )
}

export const refreshRules = (datasetId: number) =>
  Promise.all([
    mutate(rulesKey(datasetId)),
    mutate(optionsKey(datasetId)),
    mutate(eligibleTermsKey(datasetId)),
    mutate(termsKey(datasetId)),
    mutate(metricsKey(datasetId)),
  ])

async function write(datasetId: number, path: string, method: string, body?: unknown) {
  const { rule } = await apiFetch<{ rule: ExpertRule }>(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  await mutate(rulesKey(datasetId))
  return rule
}

export function createRule(input: RuleCreate) {
  return write(input.dataset_id, `${BASE}/`, "POST", input)
}

// The extension has no separate draft route: PUT on the rule saves a new draft revision when the content changed.
export function saveRuleDraft(datasetId: number, id: string, input: RuleUpdate) {
  return write(datasetId, `${BASE}/${id}`, "PUT", input)
}

export function approveRule(datasetId: number, id: string, expectedRevision: number) {
  return write(datasetId, `${BASE}/${id}/approve`, "POST", { expected_revision: expectedRevision })
}

export function revokeRule(datasetId: number, id: string, expectedRevision: number) {
  return write(datasetId, `${BASE}/${id}/revoke`, "POST", { expected_revision: expectedRevision })
}

// Approval is all or nothing, so keeping only part of a draft saves that part as a newer draft and approves it.
export async function approveRuleContent(datasetId: number, rule: ExpertRule, content: RuleContent) {
  const { rule: draft } = await apiFetch<{ rule: ExpertRule }>(`${BASE}/${rule.id}`, {
    method: "PUT",
    body: JSON.stringify({
      ...content,
      business_domain_ids: rule.business_domains.map((domain) => domain.id),
      expected_revision: rule.current.number,
    }),
  })
  return approveRule(datasetId, rule.id, draft.current.number)
}

export async function deleteRule(datasetId: number, id: string) {
  await apiFetch<unknown>(`${BASE}/${id}`, { method: "DELETE" })
  await mutate(rulesKey(datasetId))
}
