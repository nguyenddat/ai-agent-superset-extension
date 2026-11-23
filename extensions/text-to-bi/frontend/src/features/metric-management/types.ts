import type { DomainRef } from "@/features/business-model/domains"

export type MetricOrigin = "manual" | "superset"

// Manual metrics wait for a reviewer; Superset metrics are read from Superset and always count as approved.
export type MetricStatus = "draft" | "approved" | "revoked"

// Matches MetricService._manual / _native in the backend.
export type Metric = {
  id: string
  origin: MetricOrigin
  dataset_id: number
  name: string
  label: string | null
  expression: string
  description: string | null
  format: string | null
  currency: string | null
  metric_type: string | null
  warning_text: string | null
  is_active: boolean
  status: MetricStatus
  business_domains: DomainRef[]
  created_at: string | null
  updated_at: string | null
}

// Body of POST /metrics/ (MetricCreate); PATCH takes any subset of it except dataset_id (MetricPatch).
export type MetricInput = {
  dataset_id: number
  name: string
  expression: string
  label: string | null
  description: string | null
  format: string | null
  currency: string | null
  metric_type: string | null
  warning_text: string | null
  business_domain_ids: string[]
}

export type MetricPatch = Partial<Omit<MetricInput, "dataset_id">>
