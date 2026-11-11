export type DatasetColumn = {
  column_name: string;
  verbose_name?: string | null;
  type?: string | null;
  description?: string | null;
  is_dttm?: boolean;
};

export type DatasetMetric = {
  id: number;
  metric_name: string;
  verbose_name?: string | null;
  expression?: string | null;
  description?: string | null;
};

/** The intentionally redacted lifecycle state returned by metric-contract endpoints. */
export type MetricContract = {
  id: number;
  dataset_id: number;
  metric_id: number;
  metric_name: string;
  status: 'candidate' | 'approved' | 'revoked';
  /** `ai_agent`: built by the AI Agent on an aggregate dataset; while a candidate it answers users provisionally. */
  origin: 'manual' | 'ai_agent';
  owner_id: number | null;
  approver_id: number | null;
  approved_at: string | null;
  revoker_id: number | null;
  revoked_at: string | null;
  current: boolean;
};

export type MetricContractResponse = { contract: MetricContract };

export type ProposedMetric = {
  metric_name: string;
  label: string;
  expression: string;
  definition: string;
  unit: string | null;
};

/** A dataset the AI Agent drafted over base datasets; nothing runs until an administrator creates it. */
export type DatasetProposal = {
  id: number;
  name: string;
  label: string;
  description: string | null;
  sql: string;
  metric: ProposedMetric;
  sources: Array<{ id: number; name: string }>;
  question: string | null;
  status: 'pending' | 'created' | 'rejected';
  proposer_name: string | null;
  created_on: string | null;
  reviewer_name: string | null;
  reviewed_on: string | null;
  review_note: string | null;
  dataset_id: number | null;
};

export type MetricContractExecution = {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  row_count: number;
  truncated: boolean;
  /** The SQL Superset ran, RLS included; only administrators receive it. */
  sql?: string | null;
  /** True when an administrator ran a candidate that is not approved yet. */
  preview?: boolean;
  /** The metric's row kind, default filters, time window and grain this run used; null when it has none. */
  applied_defaults?: MetricAppliedDefaults | null;
};

/** What a metric means to the business; a metric needs one before it can be proposed. */
export type MetricDefinition = {
  business_definition: string;
  unit: string | null;
  steward_id: number | null;
  steward_name: string | null;
};

export type MetricDefinitionPayload = Pick<MetricDefinition, 'business_definition' | 'unit' | 'steward_id'>;

export type MetricContractEventAction = 'candidate' | 'approve' | 'revoke' | 'definition';

export type MetricContractEvent = {
  id: number;
  action: MetricContractEventAction;
  actor_id: number | null;
  actor_name: string | null;
  reason: string | null;
  expression: string | null;
  created_at: string | null;
};

export type MetricUser = { id: number; name: string };

/** Review state of a metric: `outdated` is a candidate or approval whose metric changed after it was recorded. */
export type MetricReviewState = 'not_started' | 'ineligible' | 'candidate' | 'approved' | 'outdated' | 'revoked';

/** One aggregate of a contract formula. */
export type MetricFormulaTerm = {
  aggregation: string;
  measure_column: string | null;
  measure_constant: string | null;
  condition: string | null;
};

/** A contract formula: its numerator's fields, plus a denominator and a scale when it is a ratio. */
export type MetricFormula = MetricFormulaTerm & {
  denominator: MetricFormulaTerm | null;
  scale: string | null;
  columns: string[];
};

export type MetricReviewItem = {
  dataset_id: number;
  metric_id: number;
  metric_name: string;
  verbose_name: string | null;
  description: string | null;
  expression: string | null;
  d3format: string | null;
  formula: MetricFormula | null;
  /** The expression as pseudo code with the data dictionary's column labels; null when it could not be parsed. */
  pseudo_code: string | null;
  ineligibility: string | null;
  state: MetricReviewState;
  contract: (MetricContract & { owner_name: string | null; approver_name: string | null; revoker_name: string | null }) | null;
  definition: MetricDefinition | null;
  query_defaults: MetricQueryDefaults | null;
};

/** A dataset column a metric run may group by or filter on. */
export type MetricQueryColumn = {
  column_name: string;
  verbose_name: string | null;
  type: string | null;
  is_dttm: boolean;
  groupby: boolean;
  filterable: boolean;
};

export type MetricQueryDataset = {
  id: number;
  name: string;
  columns: MetricQueryColumn[];
  /** From the data dictionary: the main time column, the row kind column and the grain of each kind of row. */
  time_column: string | null;
  row_kind_column: string | null;
  row_kinds: Array<{ value: string | null; label: string | null; grain: string }>;
  /** Date and timestamp columns a metric can be filtered by. */
  temporal_columns: string[];
};

export type MetricReviewList = {
  datasets: MetricQueryDataset[];
  metrics: MetricReviewItem[];
  users: MetricUser[];
  current_user_id: number | null;
  /** True when a proposer must leave approval to another administrator (TEXT_TO_BI_REQUIRE_SECOND_REVIEWER). */
  require_second_reviewer: boolean;
};

export type MetricFilterOperator = '==' | '!=' | '<' | '<=' | '>' | '>=' | 'IN' | 'NOT IN';

export type MetricQueryFilter = { column: string; operator: MetricFilterOperator; value: string | number | boolean | Array<string | number> };

export type MetricGrain = 'hour' | 'day' | 'week' | 'month' | 'quarter' | 'year';
export type MetricTimeAnchor = 'now' | 'latest_data';

/** How a metric is read unless a query says otherwise; changing it voids an approval like a formula edit. */
export type MetricQueryDefaults = {
  grain: MetricGrain | null;
  row_kind_column: string | null;
  row_kind_value: string | null;
  /** The grain of the rows the metric reads, from the data dictionary. */
  native_grain: string | null;
  time_column: string | null;
  /** `last_<n>_<unit>`, `current_<unit>`, `previous_<unit>` or `<unit>_to_date`. */
  time_window: string | null;
  time_anchor: MetricTimeAnchor | null;
  default_filters: MetricQueryFilter[];
};

export type MetricQueryDefaultsPayload = Pick<
  MetricQueryDefaults, 'grain' | 'row_kind_value' | 'time_column' | 'time_window' | 'time_anchor' | 'default_filters'
>;

export type MetricAppliedDefaults = {
  filters: Array<MetricQueryFilter & { source: 'row_kind' | 'default' | 'time_window' }>;
  time_window: {
    window: string;
    anchor: MetricTimeAnchor;
    column: string;
    reference: string;
    start: string;
    end: string;
    end_included: boolean;
  } | null;
  time_grain: MetricGrain | null;
};

/** A group of glossary terms with the same meaning, or of similar expert rules; membership needs no review. */
export type ConceptGroup = { id: number; name: string; description: string | null };
export type ConceptGroupReference = Pick<ConceptGroup, 'id' | 'name'>;

/** A term or rule a grouping suggestion moves: how similar it is to the rest on average, and its closest neighbour. */
export type GroupSuggestionMember = {
  id: number;
  name: string;
  similarity: number;
  closest: { id: number; name: string; similarity: number };
};
/** Ungrouped members close in meaning: for an existing `group`, or for a new group named `proposed_name`. */
export type GroupSuggestion = {
  fingerprint: string;
  group: ConceptGroupReference | null;
  proposed_name: string;
  similarity: number;
  members: GroupSuggestionMember[];
  group_members: Array<{ id: number; name: string }>;
};
/** `embedding`: compared by `model`; `tfidf`: by shared words, when no embedding model could be used. */
export type GroupSuggestionList = {
  method: 'embedding' | 'tfidf';
  model: string | null;
  threshold: number;
  suggestions: GroupSuggestion[];
};

export type GlossaryStatus = 'draft' | 'approved' | 'revoked';
/** Review state of a term: `outdated` is an approval whose linked column or metric changed since it was saved. */
export type GlossaryState = GlossaryStatus | 'outdated';
export type GlossaryLink = {
  kind: 'dataset' | 'column' | 'metric';
  dataset_id: number;
  column_name?: string | null;
  metric_id?: number | null;
  /** Readable labels, present on the admin list. */
  dataset_name?: string | null;
  target_name?: string | null;
};
export type GlossaryRevision = {
  id: number;
  revision_number: number;
  canonical_name: string;
  definition: string;
  synonyms: string[];
  status: GlossaryStatus;
  is_current: boolean;
  created_at?: string | null;
  approved_at?: string | null;
  revoked_at?: string | null;
  links: GlossaryLink[];
};
export type GlossaryTerm = {
  id: number;
  canonical_name: string;
  steward_id: number | null;
  group: ConceptGroupReference | null;
  current_revision?: GlossaryRevision | null;
  revisions?: GlossaryRevision[];
};
/** A term as the admin list returns it: its current revision with review state and the people behind it. */
export type GlossaryReviewTerm = GlossaryTerm & {
  current_revision: GlossaryRevision;
  state: GlossaryState;
  /** The approved revision the AI Agent still uses while an edit of it waits for review. */
  serving_revision_number: number | null;
  steward_name: string | null;
  author_id: number | null;
  author_name: string | null;
  approver_name: string | null;
  revoker_name: string | null;
};
export type GlossaryTermList = {
  terms: GlossaryReviewTerm[];
  groups: ConceptGroup[];
  users: MetricUser[];
  current_user_id: number | null;
  require_second_reviewer: boolean;
};
/** What a term may link to in one dataset: physical active columns and saved metrics. */
export type GlossaryDatasetOption = {
  id: number;
  name: string;
  columns: Array<{ column_name: string; name: string }>;
  metrics: Array<{ id: number; name: string }>;
};
export type GlossaryAuditEvent = {
  id: number;
  /** `moved`: the term changed group; the reason reads "old group → new group". */
  action: 'created' | 'updated' | 'approved' | 'revoked' | 'moved';
  revision_number: number | null;
  actor_id: number | null;
  actor_name: string | null;
  reason: string | null;
  created_at: string | null;
};
export type GlossaryTermPayload = {
  canonical_name: string;
  definition: string;
  synonyms: string[];
  steward_id: number | null;
  links: Array<Pick<GlossaryLink, 'kind' | 'dataset_id' | 'column_name' | 'metric_id'>>;
  group_id?: number | null;
};

export type SupersetDatabase = {
  id: number;
  database_name: string;
  /** Superset's extra JSON, as a string. */
  extra?: string | null;
};

export type DashboardDataset = {
  id: number;
  name?: string | null;
  datasource_name?: string | null;
  schema?: string | null;
  table_name?: string | null;
  description?: string | null;
  database?: { database_name?: string | null };
  columns?: DatasetColumn[];
  metrics?: DatasetMetric[];
};

export type ColumnDictionary = {
  id: number;
  column_name: string;
  display_name: string;
  data_type: string;
  nullable: boolean;
  default_value: string | null;
  is_pk: boolean;
  is_fk: boolean;
  referenced_column: string | null;
  referenced_dataset_id: number | null;
  referenced_column_name: string | null;
  referenced_dataset_label?: string | null;
  is_unique: boolean;
  unit: string | null;
  format: string | null;
  business_term: string | null;
  /** `date` or `timestamp` for a column that places rows in time; a date filter on a timestamp covers the whole day. */
  temporal_kind: TemporalKind | null;
  /** What schema link does with the column. */
  semantic_role: SemanticRole | null;
  /** Aggregations that make sense on a measure; empty when not declared. */
  aggregations: Aggregation[];
  synonyms: string[];
  description: string | null;
  /** Whether the column holds personal data (PII). */
  contains_pii?: boolean;
  /** How an administrator declared the column is computed from other columns; null when not declared. */
  transformation?: ColumnTransformation | null;
};

/** Input columns picked explicitly and a free-text expression (SQL or pseudo code) that is never parsed. */
export type ColumnTransformation = {
  expression: string | null;
  sources: Array<{ dataset_id: number; column_name: string }>;
};

export type TemporalKind = 'date' | 'timestamp';
export type SemanticRole = 'key' | 'measure' | 'dimension' | 'label' | 'time' | 'row_kind' | 'attribute';
export type Aggregation = 'SUM' | 'AVG' | 'MIN' | 'MAX' | 'COUNT' | 'COUNT_DISTINCT';
export type IndicatorAggregation = 'SUM' | 'AVG' | 'MIN' | 'MAX' | 'COUNT' | 'NONE';

/** A table that keeps one value per indicator, or the table naming the indicators. */
export type IndicatorModel =
  | { kind: 'values'; indicator_column: string; value_columns: Record<string, string> }
  | {
    kind: 'catalog';
    key_column: string;
    code_column: string;
    name_column: string;
    unit_column: string | null;
    value_kind_column: string | null;
    aggregation_column: string | null;
    aggregation_map: Record<string, IndicatorAggregation>;
  };

export type Indicator = {
  key: string | number;
  code: string | null;
  name: string | null;
  unit: string | null;
  value_kind: string | null;
  aggregation_code: string | null;
  aggregation: IndicatorAggregation | null;
};

export type IndicatorsResponse = {
  indicators: Indicator[];
  aggregation_codes: string[];
  too_many: boolean;
};

/** From finest to coarsest; `instant` rows are taken at irregular moments. */
export type Grain = 'instant' | 'hour' | 'day' | 'week' | 'month' | 'quarter' | 'year';

/** The grain of one kind of row; a dataset whose rows share one grain has a single entry with no row kind value. */
export type DatasetGrain = {
  row_kind_value: string | null;
  label: string | null;
  grain: Grain;
};

/** How the time column's values fall for one kind of row, read when an administrator asks for a suggestion. */
export type GrainProfile = {
  row_kind_value: string | null;
  row_count: number;
  first_moment: string | null;
  last_moment: string | null;
  moments: number;
  days: number;
  off_the_hour: number;
  off_midnight: number;
  off_first_day: number;
  suggested_grain: Grain | null;
};

export type GrainProfileResponse = {
  time_column: string;
  row_kind_column: string | null;
  profiles: GrainProfile[];
  too_many_kinds: boolean;
};

export type RelationshipSource = 'database' | 'dictionary' | 'naming';

/** What the last data check of a relationship found; it counts only for the snapshot it was made on. */
export type RelationshipVerification = {
  target_rows: number;
  target_unique: boolean;
  references: number;
  orphans: number;
  orphan_ratio: number;
  orphan_samples: string[];
  type_match: boolean;
  passed: boolean;
};

export type RelationshipContractView = {
  id: number;
  status: 'candidate' | 'approved' | 'revoked';
  source: RelationshipSource | null;
  cardinality: 'many_to_one' | 'one_to_one';
  /** Approved and still matching the live columns: an edge the AI Agent's schema link may join on. */
  current: boolean;
  verification: RelationshipVerification | null;
  verified_at: string | null;
};

export type RelationshipRow = {
  column_id: number;
  from_dataset_id: number;
  from_dataset_name: string;
  from_column: string;
  to_dataset_id: number;
  to_dataset_name: string;
  to_column: string;
  cardinality: 'many_to_one' | 'one_to_one' | null;
  /** Why the declared relationship cannot be a contract, such as a target that is not a key. */
  problem: string | null;
  contract: RelationshipContractView | null;
};

export type RelationshipSuggestion = {
  from_dataset_id: number;
  from_column: string;
  to_dataset_id: number;
  to_dataset_name: string;
  to_column: string;
  sources: RelationshipSource[];
  /** The source column already declares another target, which this suggestion would replace. */
  replaces: boolean;
};

export type RelationshipsResponse = {
  dataset_id: number;
  is_base: boolean;
  outgoing: RelationshipRow[];
  incoming: RelationshipRow[];
  suggestions?: RelationshipSuggestion[];
  suggestion_note?: string | null;
};

export type ReferenceDataset = {
  id: number;
  dataset_name: string;
  label: string;
  database_name?: string | null;
  schema?: string | null;
  columns: string[];
  column_types?: Record<string, string>;
  /** Columns declared as primary key or unique in the data dictionary. */
  key_columns?: Record<string, { pk: boolean; unique: boolean }>;
};

export type ColumnDictionarySuggestion = {
  column_name: string;
  display_name: string;
  unit: string | null;
  business_term: string | null;
};

export type DatasetDictionary = {
  dataset_id: number;
  dataset_name: string;
  display_name: string;
  description: string | null;
  grain: string | null;
  create_column: string | null;
  dataset_type: 'base' | 'aggregate' | null;
  layer_id: number | null;
  /** The column that places a row in time. */
  time_column: string | null;
  /** The column that tells kinds of rows of different grains apart, such as `loai_quan_sat`. */
  row_kind_column: string | null;
  grains: DatasetGrain[];
  indicator_model: IndicatorModel | null;
  columns: ColumnDictionary[];
  read_only?: boolean;
  /** Whether the table holds personal data (PII). */
  contains_pii?: boolean;
};

/**
 * Admin-defined warehouse layer. `level` is the direction data flows: layers feed the layers on higher levels, and
 * layers on one level sit side by side. `sort_order` orders all layers, level by level.
 */
export type DataLayer = {
  id: number;
  name: string;
  description: string | null;
  color: string | null;
  sort_order: number;
  level: number;
};

export type ThemeMode = 'light' | 'dark';

export type BusinessDomain = {
  id: number;
  name: string;
  description: string | null;
  color: string | null;
  dataset_ids: number[];
};

/** "flow": data moves from source into target. "relation": source references target inside one layer. */
/** `flow` and `relation` are reference edges from PK/FK; `transform` edges come from declared column transformations. */
export type LineageEdgeKind = 'flow' | 'relation' | 'transform';

export type LineageEdge = {
  source: number;
  target: number;
  kind: LineageEdgeKind;
  origin: 'dictionary' | 'manual';
  label: string | null;
  /** Display colour chosen by the user; null uses the default edge colour. */
  color: string | null;
  /** Cardinality at the source and target ends, inferred from FK declarations; absent on manual edges. */
  source_cardinality?: '1' | 'n';
  target_cardinality?: '1' | 'n';
  columns: string[];
  /** Column pairs behind the edge, oriented from its source dataset to its target; empty on manual edges. */
  column_links: Array<{ source: string; target: string }>;
  /** On transform edges: each target column fed, with its expression and all of its input columns ("table.column"). */
  transformations?: Array<{ target_column: string; expression: string | null; sources: string[] }>;
};

export type ModelMetric = {
  id: number;
  dataset_id: number;
  metric_name: string;
  verbose_name: string | null;
  description: string | null;
  expression: string | null;
  /**
   * Dataset columns the expression uses: a `measure` is a value it aggregates, a `filter` picks the rows it covers.
   * Null when the expression could not be parsed.
   */
  columns: Array<{ name: string; role: 'measure' | 'filter' }> | null;
  /** The expression as pseudo code with the data dictionary's column labels; null when it could not be parsed. */
  pseudo_code: string | null;
};

/** Stored business-view canvas: each domain's header and cells, and each table's cell, as [col, row] pairs. */
export type StoredCanvas = {
  domains: Array<{ key: string; header: [number, number]; cells: Array<[number, number]> }>;
  tables: Record<string, [number, number]>;
};

/** A lineage edge shape as stored: see EdgeGeometry, with points as [x, y] pairs. */
export type StoredEdgeShape = {
  style: 'orthogonal' | 'straight' | 'curved';
  coords: number[];
  waypoints: Array<[number, number]>;
  label: [number, number] | null;
  ports: [number, number];
};

/** Stored lineage canvas: the cards the user moved, keyed by node ID, and the edges the user shaped, by edge ID. */
export type StoredLineageCanvas = {
  nodes: Record<string, [number, number]>;
  edges: Record<string, StoredEdgeShape>;
};

export type BusinessModel = {
  /** Where the business view drew domains and tables last time, or null before the first save. */
  canvas: StoredCanvas | null;
  /** The lineage cards and edges the user placed by hand, or null before the first save. */
  lineage_canvas: StoredLineageCanvas | null;
  domains: BusinessDomain[];
  layers: DataLayer[];
  /** Data-dictionary classification of each dataset, keyed by dataset ID. */
  classifications: Record<string, { layer_id: number | null; dataset_type: DatasetDictionary['dataset_type'] }>;
  edges: LineageEdge[];
  metrics: ModelMetric[];
};

export type ExpertRuleState = 'draft' | 'approved' | 'outdated' | 'revoked';

export type ExpertRuleOperator =
  | 'equals' | 'not_equals' | 'contains' | 'not_contains' | 'greater_than' | 'greater_than_or_equal'
  | 'less_than' | 'less_than_or_equal' | 'in' | 'not_in' | 'is_null' | 'is_not_null';

export type ExpertRuleValueType = 'string' | 'number' | 'boolean' | 'null' | 'array';

export type ExpertRuleConditionValue = string | number | boolean | null | Array<string | number | boolean | null>;

export type ExpertRuleCondition = {
  field_ref: { column_dictionary_id: number };
  operator: ExpertRuleOperator;
  value_type: ExpertRuleValueType;
  value: ExpertRuleConditionValue;
};

export type ExpertRuleException = { when: string; outcome: string };

export type ExpertRuleExample = { question: string; intent: string };

export type ExpertRuleReference = { id: number; name: string };

/** One rule's current revision as the administrator review page sees it. */
export type ExpertRule = {
  id: number;
  revision: number;
  lifecycle_version: number;
  status: 'draft' | 'approved' | 'revoked';
  name: string;
  conditions: ExpertRuleCondition[];
  exceptions: ExpertRuleException[];
  examples: ExpertRuleExample[];
  dataset_id: number | null;
  dataset_name: string | null;
  group: ConceptGroupReference | null;
  state: ExpertRuleState;
  /** Display names of the dictionary columns the conditions use, keyed by column dictionary ID. */
  column_names: Record<string, string>;
  glossary_terms: ExpertRuleReference[];
  metrics: ExpertRuleReference[];
  author_id: number | null;
  author_name: string | null;
  approver_name: string | null;
  approved_at: string | null;
  revoker_name: string | null;
  revoked_at: string | null;
};

export type AgentMissingKind = 'glossary' | 'metric' | 'expert_rule';

/** What AI Agent proposed for each missing kind; an expert rule proposal leaves the threshold to the expert. */
export type AgentSuggestions = {
  glossary?: { name: string; definition: string; synonyms: string[] };
  metric?: { name: string; definition: string; unit: string };
  expert_rule?: { name: string; concept: string; description: string };
};

/** `pending` means no administrator has handled the question yet. */
export type QuestionHandlingStatus = 'pending' | 'to_create' | 'created' | 'ignored';

/** A question AI Agent could not fully resolve, as its review endpoint returns it. */
export type AgentReviewQuestion = {
  id: number;
  question: string;
  rewritten_question: string | null;
  asked_by: string | null;
  asked_on: string | null;
  glossary_terms: Array<{ id: number; name: string }>;
  metrics: Array<{ dataset_id: number; metric_id: number; name: string }>;
  expert_rules: Array<{ id: number; name: string }>;
  missing: AgentMissingKind[];
  /** False for a quantitative question, which needs no expert rule; null on questions logged before the agent asked. */
  requires_expert_rule: boolean | null;
  suggestions: AgentSuggestions;
  handling: {
    status: QuestionHandlingStatus; note: string | null; handled_by: string | null; handled_on: string | null;
  };
};

export type AgentReviewQuestionList = {
  counts: Record<QuestionHandlingStatus, number>;
  questions: AgentReviewQuestion[];
};

export type AgentDefinitionKind = 'glossary' | 'expert_rule';

/** `promoted`: a shared term or rule now covers the concept; `ignored`: it stays the user's own sense. */
export type AgentDefinitionReviewStatus = 'pending' | 'promoted' | 'ignored';

/** What one user confirmed a concept means to them on one dashboard. */
export type AgentUserDefinition = {
  id: number;
  kind: AgentDefinitionKind;
  name: string;
  concept: string | null;
  definition: string;
  user_id: number;
  defined_by: string | null;
  dashboard_id: number;
  dashboard_title: string | null;
  question: string | null;
  review_status: AgentDefinitionReviewStatus;
  reviewed_by: string | null;
  reviewed_on: string | null;
  updated_on: string | null;
};

export type ExpertRuleList = {
  rules: ExpertRule[];
  groups: ConceptGroup[];
  current_user_id: number | null;
  require_second_reviewer: boolean;
};

export type ExpertRuleAuditEntry = {
  /** `moved`: the rule changed group; the reason reads "old group → new group". */
  action: 'created' | 'updated' | 'approved' | 'revoked' | 'moved';
  revision: number;
  lifecycle_version: number;
  actor_id: number | null;
  actor_name: string | null;
  reason: string | null;
  occurred_at: string;
};

export type ExpertRuleColumnOption = { id: number; column_name: string; display_name: string; data_type: string };

/** An approved term a rule may build on, with the approved metrics and the columns it names in that dataset. */
export type ExpertRuleTermOption = ExpertRuleReference & { metric_ids: number[]; column_names: string[] };

/** A dataset a rule may be written for, with the columns, approved terms and approved metrics it may reference. */
export type ExpertRuleDatasetOption = {
  id: number;
  name: string;
  columns: ExpertRuleColumnOption[];
  glossary_terms: ExpertRuleTermOption[];
  metrics: ExpertRuleReference[];
};

export type ExpertRulePayload = {
  schema_version: 2;
  name: string;
  dataset_id: number;
  conditions: ExpertRuleCondition[];
  exceptions: ExpertRuleException[];
  examples: ExpertRuleExample[];
  glossary_term_ids: number[];
  metric_ids: number[];
  group_id?: number | null;
};

/** A CSV or XLSX file sent by the API, its bytes in base64. */
export type TableFile = { filename: string; media_type: string; content: string };

export type ImportAction = 'create' | 'update' | 'unchanged' | 'error';

/** What importing one row of a file does; `row` is the spreadsheet row number and `changes` the fields it changes. */
export type ImportRow = { row: number; key: string; action: ImportAction; message: string | null; changes: string[] };

export type ImportReport = { rows: ImportRow[]; summary: Record<ImportAction, number> };
