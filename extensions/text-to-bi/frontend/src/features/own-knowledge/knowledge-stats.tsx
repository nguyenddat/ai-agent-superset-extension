import { ArrowRightIcon, CircleXIcon, LockKeyholeIcon, UserPenIcon } from "lucide-react"

import { ColumnBars } from "@/components/stat-charts"
import { Coverage, ShareBar } from "@/components/stat-bars"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Link, pageHref } from "@/lib/navigation"
import { cn } from "@/lib/utils"

import { analyze, systemCatalog, type Findings } from "./analysis"
import { useDatabaseKnowledge } from "./knowledge-workspace"
import { KIND_ORDER, KINDS, REVIEW_STATES } from "./labels"
import { useUserNames, type UserName } from "./reviewer"
import type { KnowledgeKind, OwnEntry, ReviewStatus } from "./types"

const DAYS = 14
const USERS = 5
const STATUS_ORDER: ReviewStatus[] = ["pending", "kept_own", "promoted"]
// "Chờ duyệt" matches the glossary and rule cards, and promoted entries take the "in use" color.
const STATUS_COLORS: Record<ReviewStatus, string> = {
  pending: "var(--chart-3)",
  kept_own: "var(--chart-4)",
  promoted: "var(--chart-1)",
}

const dayKey = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
const shortDay = (key: string) => `${key.slice(8, 10)}/${key.slice(5, 7)}`

function lastDays(entries: OwnEntry[]) {
  const counts = new Map<string, number>()
  for (const entry of entries) {
    const key = dayKey(new Date(entry.created_at))
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  const today = new Date()
  return Array.from({ length: DAYS }, (_, index) => {
    const day = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (DAYS - 1 - index))
    return { name: dayKey(day), value: counts.get(dayKey(day)) ?? 0 }
  })
}

// Standalone's card reads one connection behind the review password; here it reads one Superset database's datasets,
// and the list is the admin's (require_admin), so anyone else sees a lock instead of the password form. The overview
// passes the database it shows (e.g. useDatabaseScope().databaseId); null shows the skeleton until one is known.
export function KnowledgeStatsCard({ databaseId }: { databaseId: number | null }) {
  const { entries, terms, metrics, rules, error, forbidden } = useDatabaseKnowledge(databaseId, true)
  const userName = useUserNames(!!entries)
  const href = pageHref({ section: "own-knowledge", database: databaseId })

  const all = entries ?? []
  const pending = all.filter((entry) => entry.review_status === "pending")
  const { findings } =
    entries && terms && metrics && rules
      ? analyze(all, systemCatalog(terms, metrics, rules))
      : { findings: new Map<string, Findings>() }
  const conflicted = pending.filter((entry) => (findings.get(entry.id)?.conflicts ?? 0) > 0).length
  const duplicated = pending.filter((entry) => (findings.get(entry.id)?.duplicates ?? 0) > 0).length
  const users = new Set(all.map((entry) => entry.user_id))

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Tri thức riêng của người dùng</CardTitle>
        {entries && entries.length > 0 ? (
          <CardDescription>
            {all.length} cách hiểu riêng từ {users.size} người dùng, {pending.length} mục chờ duyệt.
          </CardDescription>
        ) : null}
        <CardAction>
          <Button variant="ghost" size="sm" nativeButton={false} render={<Link href={href} />}>
            Mở duyệt
            <ArrowRightIcon data-icon="inline-end" />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-5">
        {forbidden ? (
          <Empty className="flex-1 p-4">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <LockKeyholeIcon />
              </EmptyMedia>
              <EmptyTitle>Cần quyền quản trị viên</EmptyTitle>
              <EmptyDescription>
                Số liệu này đọc từ danh sách duyệt, nên chỉ quản trị viên xem được, như ở tab Tri thức riêng.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : error ? (
          <Alert variant="destructive">
            <CircleXIcon />
            <AlertDescription>{error.message}</AlertDescription>
          </Alert>
        ) : !entries || !terms || !metrics || !rules ? (
          <Skeleton className="h-72" />
        ) : entries.length === 0 ? (
          <Empty className="flex-1 p-4">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <UserPenIcon />
              </EmptyMedia>
              <EmptyTitle>Chưa có tri thức riêng</EmptyTitle>
              <EmptyDescription>
                Khi người dùng giải thích lại một khái niệm cho AI, cách hiểu đó sẽ xuất hiện ở đây.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <>
            <Coverage
              label="Mục đã duyệt"
              unit="mục"
              doneLabel="đã giữ riêng hoặc đưa vào kho"
              done={all.length - pending.length}
              total={all.length}
              large
            />
            <ShareBar
              label="Trạng thái duyệt"
              unit="mục"
              parts={STATUS_ORDER.map((status) => ({
                key: status,
                label: REVIEW_STATES[status].label,
                value: all.filter((entry) => entry.review_status === status).length,
                color: STATUS_COLORS[status],
              }))}
            />
            <dl className="grid grid-cols-2 gap-3 border-t pt-4">
              <Figure label="Chờ duyệt, có mâu thuẫn" value={conflicted} />
              <Figure label="Chờ duyệt, có bản trùng" value={duplicated} />
            </dl>
            <ContributorGrid entries={all} userName={userName} />
            <ColumnBars
              title={`Cách hiểu mới trong ${DAYS} ngày qua`}
              unit="mục"
              rows={lastDays(all)}
              tickFormatter={shortDay}
            />
          </>
        )}
      </CardContent>
    </Card>
  )
}

function Figure({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="text-2xl font-semibold tracking-tight">{value}</dd>
    </div>
  )
}

// Who explains what: rows are the busiest users, columns the kind of knowledge, darker means more entries.
function ContributorGrid({ entries, userName }: { entries: OwnEntry[]; userName: UserName }) {
  // Counted by user id, so two users who share a display name keep their own rows.
  const byUser = new Map<number, Map<KnowledgeKind, number>>()
  for (const entry of entries) {
    const row = byUser.get(entry.user_id) ?? new Map<KnowledgeKind, number>()
    row.set(entry.kind, (row.get(entry.kind) ?? 0) + 1)
    byUser.set(entry.user_id, row)
  }
  const total = (row: Map<KnowledgeKind, number>) => [...row.values()].reduce((sum, value) => sum + value, 0)
  const ranked = [...byUser]
    .map(([id, row]) => [String(id), userName(id), row] as const)
    .sort(([, a, x], [, b, y]) => total(y) - total(x) || a.localeCompare(b, "vi"))
  const rows: (readonly [string, string, Map<KnowledgeKind, number>])[] = ranked.slice(0, USERS)
  if (ranked.length > USERS) {
    const rest = new Map<KnowledgeKind, number>()
    for (const [, , row] of ranked.slice(USERS)) {
      for (const [kind, value] of row) rest.set(kind, (rest.get(kind) ?? 0) + value)
    }
    rows.push(["rest", `${ranked.length - USERS} người khác`, rest])
  }
  const max = Math.max(...rows.flatMap(([, , row]) => [...row.values()]), 1)

  return (
    <figure className="flex flex-col gap-2">
      <figcaption className="flex items-center justify-between gap-3 text-sm font-medium">
        Ai giải thích điều gì
        <span className="flex items-center gap-1.5 text-xs font-normal text-muted-foreground" aria-hidden>
          Ít
          <span
            className={
              "h-2 w-12 rounded-sm bg-linear-to-r " +
              "from-[color-mix(in_oklch,var(--chart-1)_15%,transparent)] to-chart-1"
            }
          />
          Nhiều
        </span>
      </figcaption>
      <div className="overflow-x-auto">
        <table className="w-full border-separate border-spacing-0.5 text-sm">
          <thead>
            <tr>
              <th scope="col" className="sr-only">
                Người dùng
              </th>
              {KIND_ORDER.map((kind) => (
                <th
                  key={kind}
                  scope="col"
                  className="w-[22%] pb-1 text-center text-xs font-normal text-muted-foreground"
                >
                  {KINDS[kind].label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, user, row]) => (
              <tr key={key}>
                <th scope="row" title={user} className="max-w-0 truncate pr-2 text-left font-normal">
                  {user}
                </th>
                {KIND_ORDER.map((kind) => {
                  const value = row.get(kind) ?? 0
                  const strength = value ? 15 + Math.round((value / max) * 85) : 0
                  return (
                    <td
                      key={kind}
                      title={`${user}: ${value} ${KINDS[kind].label.toLowerCase()}`}
                      className={cn(
                        "h-7 rounded-sm text-center text-xs font-medium tabular-nums",
                        value
                          ? strength >= 55
                            ? "text-white"
                            : "text-foreground"
                          : "bg-muted/50 text-muted-foreground",
                      )}
                      style={
                        value
                          ? { background: `color-mix(in oklch, var(--chart-1) ${strength}%, transparent)` }
                          : undefined
                      }
                    >
                      {value || "·"}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  )
}
