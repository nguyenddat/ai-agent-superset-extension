import * as React from "react"
import { cn } from "cn"

// Standalone's message layout; every part forwards its ref (React 17 drops `ref` from plain function components).

const MessageGroup = React.forwardRef<HTMLDivElement, React.ComponentPropsWithoutRef<"div">>(function MessageGroup(
  { className, ...props },
  ref,
) {
  return (
    <div
      ref={ref}
      data-slot="message-group"
      className={cn("flex min-w-0 flex-col gap-2", className)}
      {...props}
    />
  )
})

type MessageProps = React.ComponentPropsWithoutRef<"div"> & { align?: "start" | "end" }

const Message = React.forwardRef<HTMLDivElement, MessageProps>(function Message(
  { className, align = "start", ...props },
  ref,
) {
  return (
    <div
      ref={ref}
      data-slot="message"
      data-align={align}
      className={cn(
        "group/message relative flex w-full min-w-0 gap-2 text-sm data-[align=end]:flex-row-reverse",
        className
      )}
      {...props}
    />
  )
})

const MessageAvatar = React.forwardRef<HTMLDivElement, React.ComponentPropsWithoutRef<"div">>(function MessageAvatar(
  { className, ...props },
  ref,
) {
  return (
    <div
      ref={ref}
      data-slot="message-avatar"
      className={cn(
        "flex w-fit min-w-8 shrink-0 items-center justify-center self-end overflow-hidden rounded-full bg-muted " +
          "group-has-data-[slot=message-footer]/message:-translate-y-8",
        className
      )}
      {...props}
    />
  )
})

const MessageContent = React.forwardRef<HTMLDivElement, React.ComponentPropsWithoutRef<"div">>(function MessageContent(
  { className, ...props },
  ref,
) {
  return (
    <div
      ref={ref}
      data-slot="message-content"
      className={cn(
        "flex w-full min-w-0 flex-col gap-2.5 wrap-break-word group-data-[align=end]/message:*:data-slot:self-end",
        className
      )}
      {...props}
    />
  )
})

const MessageHeader = React.forwardRef<HTMLDivElement, React.ComponentPropsWithoutRef<"div">>(function MessageHeader(
  { className, ...props },
  ref,
) {
  return (
    <div
      ref={ref}
      data-slot="message-header"
      className={cn(
        "flex max-w-full min-w-0 items-center px-3 text-xs font-medium text-muted-foreground " +
          "group-has-data-[variant=ghost]/message:px-0",
        className
      )}
      {...props}
    />
  )
})

const MessageFooter = React.forwardRef<HTMLDivElement, React.ComponentPropsWithoutRef<"div">>(function MessageFooter(
  { className, ...props },
  ref,
) {
  return (
    <div
      ref={ref}
      data-slot="message-footer"
      className={cn(
        "flex max-w-full min-w-0 items-center px-3 text-xs font-medium text-muted-foreground " +
          "group-has-data-[variant=ghost]/message:px-0 group-data-[align=end]/message:justify-end",
        className
      )}
      {...props}
    />
  )
})

export {
  MessageGroup,
  Message,
  MessageAvatar,
  MessageContent,
  MessageFooter,
  MessageHeader,
}
