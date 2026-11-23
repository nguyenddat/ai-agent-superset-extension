import * as React from "react"
import {
  BookOpenIcon,
  BookTextIcon,
  ExternalLinkIcon,
  LayoutDashboardIcon,
  MessageSquareTextIcon,
  NetworkIcon,
  ScaleIcon,
  SigmaIcon,
  UserPenIcon,
  WorkflowIcon,
} from "lucide-react"

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Button } from "@/components/ui/button"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { Access } from "@/lib/access"
import { Link, navigate, pageHref, useSearchParams } from "@/lib/navigation"

// Superset's navbar gets one menu per group, as the earlier extensions had: everyone asks the AI agent, data
// engineers model datasets, business owners govern what the agent may use. Every menu opens sections of the same
// page. The AI Agent comes first, right after Superset's SQL menu, where the old AI Agent extension sat.
export const sectionGroups = [
  { id: "agent", label: "AI Agent" },
  { id: "modeling", label: "Mô hình dữ liệu" },
  { id: "governance", label: "Quản trị dữ liệu" },
] as const

export type SectionGroup = (typeof sectionGroups)[number]["id"]

// The standalone app's connection sections; a section joins this list once its module has been moved to the
// extension.
export const sections = [
  {
    segment: "chat",
    group: "agent",
    label: "Hỏi dữ liệu",
    description: "Hỏi bằng ngôn ngữ tự nhiên, nhận câu trả lời, bảng số liệu và biểu đồ",
    icon: MessageSquareTextIcon,
  },
  {
    segment: "own-knowledge",
    group: "agent",
    label: "Tri thức riêng",
    description: "Duyệt tri thức người dùng dạy agent và đưa vào tri thức dùng chung",
    icon: UserPenIcon,
  },
  {
    segment: "dictionary",
    group: "modeling",
    label: "Từ điển",
    description: "Mô tả bảng và cột của dataset Superset",
    icon: BookOpenIcon,
  },
  {
    segment: "model",
    group: "modeling",
    label: "Mô hình",
    description: "Miền nghiệp vụ và tầng dữ liệu của các bảng",
    icon: NetworkIcon,
  },
  {
    segment: "lineage",
    group: "modeling",
    label: "Dòng dữ liệu",
    description: "Bảng nào tạo ra bảng nào, đến từng cột",
    icon: WorkflowIcon,
  },
  {
    segment: "",
    group: "governance",
    label: "Tổng quan",
    description: "Mức độ hoàn thiện tri thức nghiệp vụ",
    icon: LayoutDashboardIcon,
  },
  {
    segment: "metrics",
    group: "governance",
    label: "Metric",
    description: "Định nghĩa metric được quản trị",
    icon: SigmaIcon,
  },
  {
    segment: "glossary",
    group: "governance",
    label: "Thuật ngữ",
    description: "Thuật ngữ nghiệp vụ được quản trị",
    icon: BookTextIcon,
  },
  {
    segment: "rules",
    group: "governance",
    label: "Quy tắc",
    description: "Quy tắc nghiệp vụ của chuyên gia",
    icon: ScaleIcon,
  },
] as const

export type Section = (typeof sections)[number]["segment"]
type SectionItem = (typeof sections)[number]

// Who may open a section, as the backend checks it: the chat needs the query role (require_query on every dataset
// of the database), own knowledge is reviewed by admins only (its /admin routes are require_admin), and every
// modeling and governance section needs the view role (require_view).
export function canOpenSection(segment: Section, access: Access) {
  if (segment === "chat") return access.can_query
  if (segment === "own-knowledge") return access.is_admin
  return access.can_view
}

export function allowedSections(access: Access): SectionItem[] {
  return sections.filter((section) => canOpenSection(section.segment, access))
}

// Whether the user can open anything at all, i.e. whether the extension shows up for them.
export const hasAnySection = (access: Access) => allowedSections(access).length > 0

// Height left under Superset's navbar, this page header and the tabs, for sections that fill the screen (the
// equivalent of standalone's connection-layout constants). It hard-codes the height of everything above, so change
// it whenever AppShell or the header below changes height:
//   --tb-navbar  Superset's navbar, measured by index.tsx (61px unless its menu wraps)
// + 12px  AppShell main's top padding (py-3)
// + 32px  header row: the outline Button is h-8, taller than the h1's 28px line
// +  8px  nav's mt-2
// + 33px  tabs: TabsList renders 32px (base-nova's group-data-horizontal/tabs:h-8 outranks the h-10 here) + border-b
// + 12px  main's gap-3 between this header block and the section
// + 12px  main's bottom padding (py-3)
// = --tb-navbar + 109px
export const FILL_SCREEN = "lg:h-[calc(100svh-var(--tb-navbar,61px)-109px)]"
// The same height at every width, for sections that must keep everything on screen.
export const FILL_SCREEN_ALWAYS = "h-[calc(100svh-var(--tb-navbar,61px)-109px)]"

// An unknown or missing section opens the overview. With `access`, a section the user cannot open gives way to
// the first one they can (the overview for viewers, the chat for a user who may only ask questions).
export function sectionFromSearch(search: URLSearchParams, access?: Access): SectionItem {
  const requested = search.get("section") ?? ""
  const allowed = access ? allowedSections(access) : sections
  const fallback = allowed.find((section) => section.segment === "") ?? allowed[0] ?? sections.find((s) => !s.segment)!
  return allowed.find((section) => section.segment === requested) ?? fallback
}

export function useSection(access?: Access): Section {
  return sectionFromSearch(useSearchParams(), access).segment
}

// Puts the section actually shown in the address bar when the requested one was unknown or not allowed, so links,
// tabs and the navbar menu agree with the page.
export function useAllowedSection(access: Access): Section {
  const search = useSearchParams()
  const requested = search.get("section") ?? ""
  const section = sectionFromSearch(search, access).segment
  React.useEffect(() => {
    if (requested === section) return
    const params: Record<string, string> = {}
    search.forEach((value, key) => {
      params[key] = value
    })
    navigate(pageHref({ ...params, section }), { replace: true, force: true })
    // `search` is a new object every render; the two strings decide when to run.
  }, [requested, section])
  return section
}

export function WorkspaceLayout({ access, children }: { access: Access; children: React.ReactNode }) {
  const current = sectionFromSearch(useSearchParams(), access)
  const group = sectionGroups.find((item) => item.id === current.group) ?? sectionGroups[0]
  const siblings = allowedSections(access).filter((section) => section.group === group.id)

  return (
    <>
      <div className="flex flex-col">
        {/* min-h-8 keeps the row as tall as the dataset button, which the AI Agent group does not show: the
            FILL_SCREEN heights above count on it. */}
        <header className="flex min-h-8 items-center justify-between gap-3">
          <Breadcrumb aria-label="Đường dẫn" className="min-w-0">
            <BreadcrumbList className="m-0 list-none flex-nowrap gap-2 p-0">
              <BreadcrumbItem className="shrink-0">
                <BreadcrumbLink
                  className="text-muted-foreground"
                  render={<Link href={pageHref({ section: siblings[0].segment })} />}
                >
                  {group.label}
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem className="min-w-0 gap-2.5">
                <h1 aria-current="page" className="truncate text-xl font-semibold tracking-tight text-foreground">
                  {current.label}
                </h1>
                <span className="hidden truncate text-muted-foreground md:inline">{current.description}</span>
              </BreadcrumbItem>
            </BreadcrumbList>
          </Breadcrumb>
          {group.id !== "agent" && (
            <Button
              variant="outline"
              className="shrink-0"
              nativeButton={false}
              render={<a href="/tablemodelview/list/" />}
            >
              <ExternalLinkIcon data-icon="inline-start" />
              <span className="hidden sm:inline">Dataset Superset</span>
            </Button>
          )}
        </header>
        <nav aria-label={`Mục của ${group.label}`} className="mt-2 overflow-x-auto overflow-y-hidden border-b">
          <Tabs value={current.segment}>
            <TabsList variant="line" className="h-10 w-full min-w-max justify-start">
              {siblings.map(({ segment, label, icon: Icon }) => (
                <TabsTrigger
                  key={segment}
                  value={segment}
                  // A group holds only a few sections, so tabs keep their own width instead of sharing the row.
                  className="flex-none px-3"
                  nativeButton={false}
                  render={<Link href={pageHref({ section: segment })} />}
                >
                  <Icon />
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </nav>
      </div>

      {children}
    </>
  )
}
