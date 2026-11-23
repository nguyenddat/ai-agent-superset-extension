import { useState } from "react"

import { Toaster } from "@/components/toaster"
import { TooltipProvider } from "@/components/ui/tooltip"
import { PortalContainerContext } from "@/lib/portal-container"

// The extension's root inside Superset: theme tokens are scoped to `.tb-page`, and popups portal into it so they
// keep those tokens. Superset draws the site header, so this only frames the content under it.
export function AppShell({ children }: { children: React.ReactNode }) {
  const [root, setRoot] = useState<HTMLDivElement | null>(null)

  return (
    <div ref={setRoot} className="tb-page flex min-h-[calc(100svh-var(--tb-navbar,61px))] flex-col bg-background text-sm text-foreground">
      <PortalContainerContext.Provider value={root}>
        <TooltipProvider>
          <main className="flex w-full flex-col gap-3 px-3 py-3 sm:px-4">{children}</main>
          <Toaster />
        </TooltipProvider>
      </PortalContainerContext.Provider>
    </div>
  )
}
