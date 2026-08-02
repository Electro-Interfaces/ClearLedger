// Tremor Callout [v0.0.1]

import React from "react"
import { tv, type VariantProps } from "tailwind-variants"

import { cn } from "@/lib/utils"

const calloutVariants = tv({
  base: "flex flex-col overflow-hidden rounded-md p-4 text-sm",
  variants: {
    variant: {
      default: [
        // text color
        "text-primary",
        // background color
        "bg-primary/10",
      ],
      success: [
        // text color
        "text-success",
        // background color
        "bg-success/10",
      ],
      error: [
        // text color
        "text-error",
        // background color
        "bg-error/10",
      ],
      warning: [
        // text color
        "text-warning",
        // background color
        "bg-warning/10",
      ],
      neutral: [
        // text color
        "text-foreground",
        // background color
        "bg-muted",
      ],
    },
  },
  defaultVariants: {
    variant: "default",
  },
})

interface CalloutProps
  extends React.ComponentPropsWithoutRef<"div">,
    VariantProps<typeof calloutVariants> {
  title: string
  icon?: React.ElementType | React.ReactElement
}

const Callout = React.forwardRef<HTMLDivElement, CalloutProps>(
  (
    { title, icon: Icon, className, variant, children, ...props }: CalloutProps,
    forwardedRef,
  ) => {
    return (
      <div
        ref={forwardedRef}
        className={cn(calloutVariants({ variant }), className)}
       
        {...props}
      >
        <div className={cn("flex items-start")}>
          {Icon && typeof Icon === "function" ? (
            <Icon
              className={cn("mr-1.5 h-5 w-5 shrink-0")}
              aria-hidden="true"
            />
          ) : (
            Icon
          )}
          <span className={cn("font-semibold")}>{title}</span>
        </div>
        <div className={cn("overflow-y-auto", children ? "mt-2" : "")}>
          {children}
        </div>
      </div>
    )
  },
)

Callout.displayName = "Callout"

export { Callout, calloutVariants, type CalloutProps }
