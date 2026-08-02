// Tremor ProgressCircle [v0.0.3]

import React from "react"
import { tv, type VariantProps } from "tailwind-variants"

import { cn } from "@/lib/utils"

const progressCircleVariants = tv({
  slots: {
    background: "",
    circle: "",
  },
  variants: {
    variant: {
      default: {
        background: "stroke-primary/20",
        circle: "stroke-primary",
      },
      neutral: {
        background: "stroke-muted-foreground/20",
        circle: "stroke-muted-foreground",
      },
      warning: {
        background: "stroke-warning/20",
        circle: "stroke-warning",
      },
      error: {
        background: "stroke-error/20",
        circle: "stroke-error",
      },
      success: {
        background: "stroke-success/20",
        circle: "stroke-success",
      },
    },
  },
  defaultVariants: {
    variant: "default",
  },
})

interface ProgressCircleProps
  extends Omit<React.SVGProps<SVGSVGElement>, "value">,
    VariantProps<typeof progressCircleVariants> {
  value?: number
  max?: number
  showAnimation?: boolean
  radius?: number
  strokeWidth?: number
  children?: React.ReactNode
}

const ProgressCircle = React.forwardRef<SVGSVGElement, ProgressCircleProps>(
  (
    {
      value = 0,
      max = 100,
      radius = 32,
      strokeWidth = 6,
      showAnimation = true,
      variant,
      className,
      children,
      ...props
    }: ProgressCircleProps,
    forwardedRef,
  ) => {
    const safeValue = Math.min(max, Math.max(value, 0))
    const normalizedRadius = radius - strokeWidth / 2
    const circumference = normalizedRadius * 2 * Math.PI
    const offset = circumference - (safeValue / max) * circumference

    const { background, circle } = progressCircleVariants({ variant })
    return (
      <div
        className={cn("relative")}
        role="progressbar"
        aria-label="Progress circle"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
        data-max={max}
        data-value={safeValue ?? null}
       
      >
        <svg
          ref={forwardedRef}
          width={radius * 2}
          height={radius * 2}
          viewBox={`0 0 ${radius * 2} ${radius * 2}`}
          className={cn("-rotate-90 transform", className)}
          {...props}
        >
          <circle
            r={normalizedRadius}
            cx={radius}
            cy={radius}
            strokeWidth={strokeWidth}
            fill="transparent"
            stroke=""
            strokeLinecap="round"
            className={cn("transition-colors ease-linear", background())}
          />
          {safeValue >= 0 ? (
            <circle
              r={normalizedRadius}
              cx={radius}
              cy={radius}
              strokeWidth={strokeWidth}
              strokeDasharray={`${circumference} ${circumference}`}
              strokeDashoffset={offset}
              fill="transparent"
              stroke=""
              strokeLinecap="round"
              className={cn(
                "transition-colors ease-linear",
                circle(),
                showAnimation &&
                  "transform-gpu transition-all duration-300 ease-in-out",
              )}
            />
          ) : null}
        </svg>
        <div
          className={cn("absolute inset-0 flex items-center justify-center")}
        >
          {children}
        </div>
      </div>
    )
  },
)

ProgressCircle.displayName = "ProgressCircle"

export { ProgressCircle, type ProgressCircleProps }
