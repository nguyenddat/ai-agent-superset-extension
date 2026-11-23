import type { DomainRef } from "@/features/business-model/domains"

// Shapes follow the extension backend (modules/glossary_management), not the standalone app: a term belongs to a
// Superset dataset, and a link names its target by key (dataset ID, column name, metric ID).
export type LinkKind = "table" | "column" | "metric" | "superset_metric"
export type RevisionStatus = "draft" | "approved" | "revoked"

export type GlossaryLink = {
  kind: LinkKind
  target_key: string
}

export type GlossaryRevision = {
  number: number
  status: RevisionStatus
  definition: string
  synonyms: string[]
  links: GlossaryLink[]
  created_at: string
}

export type GlossaryTerm = {
  id: string
  dataset_id: number
  canonical_name: string
  business_domains: DomainRef[]
  current: GlossaryRevision
  serving: GlossaryRevision | null
  created_at: string
  updated_at: string
}

export type GlossaryContent = {
  definition: string
  synonyms: string[]
  links: GlossaryLink[]
}

export type GlossaryCreate = GlossaryContent & {
  dataset_id: number
  canonical_name: string
  business_domain_ids: string[]
}

export type GlossaryUpdate = GlossaryContent & {
  expected_revision: number
  business_domain_ids: string[]
}

// The part of GET /metrics/datasets/<id> that links need: manual metrics plus Superset's own.
export type DatasetMetric = {
  id: string
  origin: "manual" | "superset"
  dataset_id: number
  name: string
  label: string | null
  expression: string
  is_active: boolean
  status: RevisionStatus
}

export type BusinessDomain = DomainRef & { description: string | null; dataset_ids: number[] }
