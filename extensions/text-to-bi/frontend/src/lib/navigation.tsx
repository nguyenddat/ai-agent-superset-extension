import { type AnchorHTMLAttributes, forwardRef, type MouseEvent, useEffect, useState } from "react"

// The whole extension lives on one Superset page, so sections and the open dataset are kept in the query string,
// the way the standalone app keeps them in its routes.
export const PAGE_PATH = "/text-to-bi/"

export const CHANGE_EVENT = "text-to-bi:navigate"

export function pageHref(params: Record<string, string | number | null | undefined>) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value))
  }
  const query = search.toString()
  return query ? `${PAGE_PATH}?${query}` : PAGE_PATH
}

// Switching section never unloads the page, so `beforeunload` cannot protect unsaved edits; an editor with
// unsaved edits sets a message here and section links ask before leaving.
let leaveWarning: string | null = null

export function setLeaveWarning(message: string | null) {
  leaveWarning = message
}

// `force` is for a caller that has already asked the user, e.g. through its own dialog.
export function navigate(href: string, { replace = false, force = false }: { replace?: boolean; force?: boolean } = {}) {
  if (leaveWarning && !force && !window.confirm(leaveWarning)) return
  leaveWarning = null
  if (replace) window.history.replaceState(null, "", href)
  else window.history.pushState(null, "", href)
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

export function useSearchParams() {
  const [search, setSearch] = useState(() => window.location.search)

  useEffect(() => {
    const sync = () => setSearch(window.location.search)
    window.addEventListener("popstate", sync)
    window.addEventListener(CHANGE_EVENT, sync)
    return () => {
      window.removeEventListener("popstate", sync)
      window.removeEventListener(CHANGE_EVENT, sync)
    }
  }, [])

  return new URLSearchParams(search)
}

// A plain anchor that switches section without reloading Superset; a modified click still opens a new tab.
export const Link = forwardRef<HTMLAnchorElement, AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }>(
  function Link({ href, onClick, ...props }, ref) {
    const open = (event: MouseEvent<HTMLAnchorElement>) => {
      onClick?.(event)
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return
      event.preventDefault()
      navigate(href)
    }
    return <a ref={ref} href={href} onClick={open} {...props} />
  },
)
