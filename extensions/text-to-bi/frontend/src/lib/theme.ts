import { useCallback } from "react"

import { usePortalContainer } from "@/lib/portal-container"
import { useSyncExternalStore } from "@/lib/react-compat"

export type ColorMode = "light" | "dark"

// index.tsx stamps data-theme-mode on the page host and re-stamps it whenever Superset's theme changes; this stands in
// for next-themes' resolvedTheme, e.g. React Flow's colorMode.
function themeHost(root: Element | undefined) {
  return (root ?? document.querySelector(".tb-page"))?.closest("[data-theme-mode]") ?? null
}

const modeOf = (host: Element | null): ColorMode =>
  host?.getAttribute("data-theme-mode") === "dark" ? "dark" : "light"

export function useColorMode(): ColorMode {
  const root = usePortalContainer()

  const subscribe = useCallback(
    (onChange: () => void) => {
      const host = themeHost(root)
      if (!host) return () => undefined
      const observer = new MutationObserver(onChange)
      observer.observe(host, { attributes: true, attributeFilter: ["data-theme-mode"] })
      return () => observer.disconnect()
    },
    [root],
  )

  return useSyncExternalStore(subscribe, () => modeOf(themeHost(root)))
}
