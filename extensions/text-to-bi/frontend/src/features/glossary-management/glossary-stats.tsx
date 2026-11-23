import { ArrowRightIcon, BookTextIcon, CircleXIcon } from "lucide-react"

import { GroupBars } from "@/components/stat-charts"
import { Coverage, ShareBar } from "@/components/stat-bars"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Link, pageHref } from "@/lib/navigation"

import { useDictionarySummary } from "../data-dictionary/api"
import { allDatasets } from "../data-dictionary/dataset-groups"
import { useAllGlossaries } from "./api"
import { groupByDomain, NO_DOMAIN } from "@/features/business-model/domains"
import { TERM_STATES, termState, type TermState } from "./labels"

// Shared states keep one color across the glossary and rule cards; "in use" is always the first slot.
const COLORS: Record<TermState, string> = {
  approved: "var(--chart-1)",
  changed: "var(--chart-2)",
  draft: "var(--chart-3)",
  revoked: "var(--muted-foreground)",
}

// Standalone counts one connection; the overview here counts every dataset the user may read, and a dataset with an
// approved term stands in for standalone's table with approved terms.
export function GlossaryStatsCard() {
  const { data: summary, error: summaryError } = useDictionarySummary()
  const datasets = summary ? allDatasets(summary) : null
  const { data: lists, error: termsError } = useAllGlossaries(datasets?.map((dataset) => dataset.dataset_id) ?? null)
  const error = (summaryError ?? termsError) as Error | undefined
  const href = pageHref({ section: "glossary" })

  const terms = lists?.flatMap((list) => list.terms)
  const states = new Map<TermState, number>()
  for (const term of terms ?? []) states.set(termState(term), (states.get(termState(term)) ?? 0) + 1)
  const serving = (terms ?? []).filter((term) => term.serving).length
  const live = (terms ?? []).filter((term) => term.current.status !== "revoked")
  const groups = groupByDomain(live, (term) => term.business_domains)
  const synonyms = live.reduce((sum, term) => sum + term.current.synonyms.length, 0)

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Thuật ngữ AI đang dùng</CardTitle>
        {terms && terms.length > 0 ? (
          <CardDescription>
            {live.length} thuật ngữ còn hiệu lực, {synonyms} từ đồng nghĩa.
          </CardDescription>
        ) : null}
        <CardAction>
          <Button variant="ghost" size="sm" nativeButton={false} render={<Link href={href} />}>
            Mở thuật ngữ
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-5">
        {error ? (
          <Alert variant="destructive">
            <CircleXIcon />
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        ) : !terms || !lists ? (
          <Skeleton className="h-72" />
        ) : terms.length === 0 ? (
          <Empty className="flex-1 p-4">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <BookTextIcon />
              </EmptyMedia>
              <EmptyTitle>Chưa có thuật ngữ</EmptyTitle>
              <EmptyDescription>
                Định nghĩa các từ nghiệp vụ như Khách hàng mới để AI hiểu đúng câu hỏi.
              </EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button size="sm" variant="outline" nativeButton={false} render={<Link href={href} />}>
                Thêm thuật ngữ
              </Button>
            </EmptyContent>
          </Empty>
        ) : (
          <>
            <Coverage
              label="Thuật ngữ"
              unit="thuật ngữ"
              doneLabel="AI đang dùng"
              done={serving}
              total={terms.length}
              large
            />
            <ShareBar
              label="Trạng thái thuật ngữ"
              unit="thuật ngữ"
              parts={(Object.keys(TERM_STATES) as TermState[]).map((state) => ({
                key: state,
                label: TERM_STATES[state].label,
                value: states.get(state) ?? 0,
                color: COLORS[state],
              }))}
            />
            <div className="flex flex-col gap-4 border-t pt-4">
              <Coverage
                label="Bảng có thuật ngữ đã duyệt"
                unit="bảng"
                doneLabel="có thuật ngữ đã duyệt"
                done={lists.filter((list) => list.terms.some((term) => term.serving)).length}
                total={lists.length}
              />
              {groups.length > 0 ? (
                <GroupBars
                  title="Thuật ngữ còn hiệu lực theo miền nghiệp vụ"
                  unit="thuật ngữ"
                  rows={groups.map((group) => ({ name: group.domain?.name ?? NO_DOMAIN, value: group.items.length }))}
                />
              ) : null}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
