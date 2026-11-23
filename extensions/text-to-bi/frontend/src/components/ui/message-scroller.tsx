import * as React from "react"
import { cn } from "cn"

import { Button } from "@/components/ui/button"
import {
  MessageScroller as MessageScrollerPrimitive,
  type MessageScrollerButtonProps,
  type MessageScrollerContentProps,
  type MessageScrollerItemProps,
  type MessageScrollerProps,
  type MessageScrollerProviderProps,
  type MessageScrollerViewportProps,
  useMessageScroller,
  useMessageScrollerScrollable,
  useMessageScrollerVisibility,
} from "@/lib/message-scroller"
import { ArrowDownIcon } from "lucide-react"

// Standalone's styled message scroller over lib/message-scroller, the React 17 port of @shadcn/react's primitive.
// The parts are forwardRef'd because React 17 drops `ref` from plain function components.

function MessageScrollerProvider(props: MessageScrollerProviderProps) {
  return <MessageScrollerPrimitive.Provider {...props} />
}

const MessageScroller = React.forwardRef<HTMLDivElement, MessageScrollerProps>(function MessageScroller(
  { className, ...props },
  ref,
) {
  return (
    <MessageScrollerPrimitive.Root
      ref={ref}
      data-slot="message-scroller"
      className={cn("group/message-scroller relative flex size-full min-h-0 flex-col overflow-hidden", className)}
      {...props}
    />
  )
})

const MessageScrollerViewport = React.forwardRef<HTMLDivElement, MessageScrollerViewportProps>(
  function MessageScrollerViewport({ className, ...props }, ref) {
    return (
      <MessageScrollerPrimitive.Viewport
        ref={ref}
        data-slot="message-scroller-viewport"
        className={cn(
          "size-full min-h-0 min-w-0 scroll-fade-b scrollbar-thin scrollbar-gutter-stable overflow-y-auto " +
            "overscroll-contain contain-content data-autoscrolling:scrollbar-thumb-transparent " +
            "data-autoscrolling:scrollbar-track-transparent data-pending-scroll:invisible",
          className
        )}
        {...props}
      />
    )
  }
)

const MessageScrollerContent = React.forwardRef<HTMLDivElement, MessageScrollerContentProps>(
  function MessageScrollerContent({ className, ...props }, ref) {
    return (
      <MessageScrollerPrimitive.Content
        ref={ref}
        data-slot="message-scroller-content"
        className={cn("flex h-max min-h-full flex-col gap-6", className)}
        {...props}
      />
    )
  }
)

const MessageScrollerItem = React.forwardRef<HTMLDivElement, MessageScrollerItemProps>(function MessageScrollerItem(
  { className, scrollAnchor = false, ...props },
  ref,
) {
  return (
    <MessageScrollerPrimitive.Item
      ref={ref}
      data-slot="message-scroller-item"
      scrollAnchor={scrollAnchor}
      className={cn("min-w-0 shrink-0 [contain-intrinsic-size:auto_10rem] [content-visibility:auto]", className)}
      {...props}
    />
  )
})

const MessageScrollerButton = React.forwardRef<
  HTMLButtonElement,
  MessageScrollerButtonProps & Pick<React.ComponentProps<typeof Button>, "variant" | "size">
>(function MessageScrollerButton(
  { direction = "end", className, children, render, variant = "secondary", size = "icon-sm", ...props },
  ref,
) {
  return (
    <MessageScrollerPrimitive.Button
      ref={ref}
      data-slot="message-scroller-button"
      data-variant={variant}
      data-size={size}
      direction={direction}
      className={cn(
        "absolute inset-s-1/2 -translate-x-1/2 border-border bg-background text-foreground " +
          "transition-[translate,scale,opacity] duration-200 hover:bg-muted hover:text-foreground " +
          "data-[active=false]:pointer-events-none data-[active=false]:scale-95 data-[active=false]:opacity-0 " +
          "data-[active=false]:duration-400 data-[active=false]:ease-[cubic-bezier(0.7,0,0.84,0)] " +
          "data-[active=true]:translate-y-0 data-[active=true]:scale-100 data-[active=true]:opacity-100 " +
          "data-[active=true]:ease-[cubic-bezier(0.23,1,0.32,1)] data-[direction=end]:bottom-4 " +
          "data-[direction=end]:data-[active=false]:translate-y-full data-[direction=start]:top-4 " +
          "data-[direction=start]:data-[active=false]:-translate-y-full rtl:translate-x-1/2 " +
          "data-[direction=start]:[&_svg]:rotate-180",
        className
      )}
      render={render ?? <Button variant={variant} size={size} />}
      {...props}
    >
      {children ?? (
        <>
          <ArrowDownIcon />
          <span className="sr-only">{direction === "end" ? "Cuộn xuống cuối" : "Cuộn lên đầu"}</span>
        </>
      )}
    </MessageScrollerPrimitive.Button>
  )
})

export {
  MessageScrollerProvider,
  MessageScroller,
  MessageScrollerViewport,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerButton,
  useMessageScroller,
  useMessageScrollerScrollable,
  useMessageScrollerVisibility,
}
