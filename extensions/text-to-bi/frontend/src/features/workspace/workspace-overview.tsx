import { ModelStatsCard } from "../business-model/model-stats"
import { DictionaryCoverageCard, DictionaryRankCards } from "../data-dictionary/dictionary-stats"
import { RuleStatsCard } from "../expert-rule-management/rule-stats"
import { LineageStatsCard } from "../data-lineage/lineage-stats"
import { GlossaryStatsCard } from "../glossary-management/glossary-stats"
import { MetricStatsCard } from "../metric-management/metric-stats"
import { KnowledgeStatsCard } from "../own-knowledge/knowledge-stats"
import type { Access } from "@/lib/access"
import { useDatabaseScope } from "./database-scope"

// The standalone overview in its order. The database-scoped cards follow the database picked on those sections (or the
// first one), as standalone's follow its connection; own knowledge is for admins only, like its review routes.
export function WorkspaceOverview({ access }: { access: Access }) {
  const { databaseId } = useDatabaseScope()
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <DictionaryCoverageCard />
      </div>
      <DictionaryRankCards />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <ModelStatsCard databaseId={databaseId} />
        {databaseId !== null ? <LineageStatsCard databaseId={databaseId} /> : null}
        <MetricStatsCard />
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <GlossaryStatsCard />
        <RuleStatsCard />
        {access.is_admin ? <KnowledgeStatsCard databaseId={databaseId} /> : null}
      </div>
    </div>
  )
}
