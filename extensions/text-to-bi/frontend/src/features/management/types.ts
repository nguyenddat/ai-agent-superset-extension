export type DomainRef = { id: string; name: string; color: string | null };
export type DatasetRef = { dataset_id: number; display_name: string; schema_name: string | null; table_name: string };
export type Summary = { databases: Array<{ database_name: string; schemas: Array<{ tables: DatasetRef[] }> }> };
export type Access = {
  is_admin: boolean; can_view: boolean; can_edit: boolean; can_query: boolean; can_review: boolean;
};

export type Metric = {
  id: string; origin: 'manual' | 'superset'; dataset_id: number; name: string; label: string | null;
  expression: string; description: string | null; format: string | null; currency: string | null;
  metric_type: string | null; warning_text: string | null; is_active: boolean;
  status: 'draft' | 'approved' | 'revoked'; business_domains: DomainRef[];
  created_at: string | null; updated_at: string | null;
};
export type MetricInput = {
  dataset_id: number; name: string; expression: string; label: string | null; description: string | null;
  format: string | null; currency: string | null; metric_type: string | null; warning_text: string | null;
  business_domain_ids: string[];
};

export type GlossaryLink = { kind: 'table' | 'column' | 'metric' | 'superset_metric'; target_key: string };
export type TermRevision = {
  number: number; status: 'draft' | 'approved' | 'revoked'; definition: string;
  synonyms: string[]; links: GlossaryLink[]; created_at: string;
};
export type Term = {
  id: string; dataset_id: number; canonical_name: string; business_domains: DomainRef[];
  current: TermRevision; serving: TermRevision | null; created_at: string; updated_at: string;
};
export type TermInput = {
  dataset_id: number; canonical_name: string; definition: string; synonyms: string[];
  links: GlossaryLink[]; business_domain_ids: string[];
};

export type Condition = {
  column_name: string; operator: string; value_type: 'string' | 'number' | 'boolean' | 'null' | 'array';
  value: unknown;
};
export type MetricRef = { kind: 'metric' | 'superset_metric'; target_key: string };
export type RuleRevision = {
  number: number; status: 'draft' | 'approved' | 'revoked'; description: string | null;
  conditions: Condition[]; exceptions: Array<{ when: string; outcome: string }>;
  examples: Array<{ question: string; intent: string }>;
  glossary_term_ids: string[]; metric_refs: MetricRef[]; created_at: string;
};
export type Rule = {
  id: string; dataset_id: number; name: string; business_domains: DomainRef[];
  current: RuleRevision; serving: RuleRevision | null; is_discoverable: boolean;
  created_at: string; updated_at: string;
};
export type RuleInput = {
  dataset_id: number; name: string; description: string | null; conditions: Condition[];
  exceptions: Array<{ when: string; outcome: string }>;
  examples: Array<{ question: string; intent: string }>;
  glossary_term_ids: string[]; metric_refs: MetricRef[]; business_domain_ids: string[];
};
export type RuleOptions = {
  dataset_id: number; columns: Array<{ name: string; data_type: string }>;
  glossary_terms: Array<{ id: string; name: string }>;
  metrics: Metric[];
};
