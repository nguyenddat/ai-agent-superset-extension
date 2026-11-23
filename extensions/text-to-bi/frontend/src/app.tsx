import { AppShell } from "@/components/layout/app-shell"
import { ModelWorkspace } from "@/features/business-model/model-workspace"
import { DictionaryWorkspace } from "@/features/data-dictionary/dictionary-workspace"
import { LineageWorkspace } from "@/features/data-lineage/lineage-workspace"
import { RuleWorkspace } from "@/features/expert-rule-management/rule-workspace"
import { GlossaryWorkspace } from "@/features/glossary-management/glossary-workspace"
import { MetricWorkspace } from "@/features/metric-management/metric-workspace"
import { KnowledgeWorkspace } from "@/features/own-knowledge/knowledge-workspace"
import { ChatWorkspace } from "@/features/text2sql/chat-workspace"
import type { Access } from "@/lib/access"
import { hasAnySection, useAllowedSection, WorkspaceLayout } from "@/features/workspace/workspace-layout"
import { WorkspaceOverview } from "@/features/workspace/workspace-overview"

// Stands in for the standalone app's routes: one component per section of the page. Only sections the user may
// open are reached; any other request is sent to one they can (useAllowedSection).
function SectionContent({ access }: { access: Access }) {
  const section = useAllowedSection(access)
  if (section === "chat") return <ChatWorkspace access={access} />
  if (section === "own-knowledge") return <KnowledgeWorkspace access={access} />
  if (section === "dictionary") return <DictionaryWorkspace />
  if (section === "model") return <ModelWorkspace access={access} />
  if (section === "lineage") return <LineageWorkspace access={access} />
  if (section === "metrics") return <MetricWorkspace access={access} />
  if (section === "glossary") return <GlossaryWorkspace access={access} />
  if (section === "rules") return <RuleWorkspace access={access} />
  return <WorkspaceOverview access={access} />
}

export function App({ access }: { access: Access }) {
  return (
    <AppShell>
      {hasAnySection(access) ? (
        <WorkspaceLayout access={access}>
          <SectionContent access={access} />
        </WorkspaceLayout>
      ) : (
        <p className="py-10 text-center text-muted-foreground">Bạn chưa được cấp quyền dùng Text to BI.</p>
      )}
    </AppShell>
  )
}
