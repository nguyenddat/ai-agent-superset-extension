import type { DomainRef } from "@/features/business-model/domains"

// Mirrors modules/expert_rule_management/schemas/schema_expert_rule.py and ExpertRuleService._serialize.

export type Operator =
  | "equals"
  | "not_equals"
  | "contains"
  | "not_contains"
  | "greater_than"
  | "greater_than_or_equal"
  | "less_than"
  | "less_than_or_equal"
  | "in"
  | "not_in"
  | "is_null"
  | "is_not_null"

export type ValueType = "string" | "number" | "boolean" | "null" | "array"
export type Scalar = string | number | boolean
export type RevisionStatus = "draft" | "approved" | "revoked"

// A condition names its column: Superset may drop and recreate `table_columns` rows when a dataset is synced.
export type RuleCondition = {
  column_name: string
  operator: Operator
  value_type: ValueType
  value: Scalar | Scalar[] | null
}

export type RuleException = { when: string; outcome: string }
export type RuleExample = { question: string; intent: string }

// `metric` is a metric managed here (UUID), `superset_metric` one of the dataset's own Superset metrics (numeric id).
export type MetricKind = "metric" | "superset_metric"
export type MetricRef = { kind: MetricKind; target_key: string }

export type RuleContent = {
  description: string | null
  conditions: RuleCondition[]
  exceptions: RuleException[]
  examples: RuleExample[]
  glossary_term_ids: string[]
  metric_refs: MetricRef[]
}

export type RuleRevision = RuleContent & {
  number: number
  status: RevisionStatus
  created_at: string
}

export type ExpertRule = {
  id: string
  dataset_id: number
  name: string
  business_domains: DomainRef[]
  current: RuleRevision
  serving: RuleRevision | null
  is_discoverable: boolean
  created_at: string
  updated_at: string
}

export type RuleCreate = RuleContent & {
  dataset_id: number
  name: string
  business_domain_ids: string[]
}

export type RuleUpdate = RuleContent & {
  expected_revision: number
  business_domain_ids: string[]
}

export type OptionColumn = { name: string; data_type: string }

// The metric payload of modules/metric_management (MetricService._manual / _native).
export type RuleMetric = {
  id: string
  origin: "manual" | "superset"
  dataset_id: number
  name: string
  label: string | null
  expression: string
  description: string | null
  is_active: boolean
  status: "draft" | "approved" | "revoked"
}

// GET /expert-rules/datasets/<id>/options
export type RuleOptions = {
  dataset_id: number
  columns: OptionColumn[]
  glossary_terms: { id: string; name: string }[]
  metrics: RuleMetric[]
}

// The parts of a glossary term (GET /glossary/datasets/<id>) a rule shows for the terms it links.
export type RuleTerm = {
  id: string
  dataset_id: number
  canonical_name: string
  current: { number: number; status: RevisionStatus }
  serving: { number: number; status: RevisionStatus } | null
}

// GET /glossary/datasets/<id>/discovery: approved terms with the links that still resolve on the dataset.
export type DiscoveryTerm = { id: string; name: string; links: unknown[] }
