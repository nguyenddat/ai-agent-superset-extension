"use client"

import * as React from "react"
import { Collapsible as CollapsiblePrimitive } from "@base-ui/react/collapsible"

function Collapsible({ ...props }: CollapsiblePrimitive.Root.Props) {
  return <CollapsiblePrimitive.Root data-slot="collapsible" {...props} />
}

// forwardRef: under React 17 a trigger nested through another part's `render` would otherwise drop the ref
// its popup anchors to.
const CollapsibleTrigger = React.forwardRef<
  React.ElementRef<typeof CollapsiblePrimitive.Trigger>,
  CollapsiblePrimitive.Trigger.Props
>(function CollapsibleTrigger(props, ref) {
  return <CollapsiblePrimitive.Trigger ref={ref} data-slot="collapsible-trigger" {...props} />
})

function CollapsibleContent({ ...props }: CollapsiblePrimitive.Panel.Props) {
  return (
    <CollapsiblePrimitive.Panel data-slot="collapsible-content" {...props} />
  )
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
