// The contract of the extension's own-knowledge API (modules/own_knowledge, EntryOut): standalone's types, rewritten
// for Superset, where an entry belongs to a dataset and users are Superset users (integer ids). The backend keeps no
// table id apart from the dataset, and records the signed-in admin as the reviewer.
export type KnowledgeKind = "glossary" | "metric" | "expert_rule"
export type ReviewStatus = "pending" | "kept_own" | "promoted"

export type OwnEntry = {
  id: string
  dataset_id: number
  user_id: number
  kind: KnowledgeKind
  name: string
  concept: string | null
  definition: string
  source_clarification_id: string | null
  source_proposal_id: string | null
  source_question: string | null
  review_status: ReviewStatus
  review_note: string | null
  reviewed_by: number | null
  reviewed_at: string | null
  promoted_kind: KnowledgeKind | null
  promoted_id: string | null
  version: number
  created_at: string
  updated_at: string
  active_for_agent: boolean
}

export type ReviewAction = "keep_own" | "reopen"
