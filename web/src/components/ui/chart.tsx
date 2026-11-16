import * as React from "react"
import * as RechartsPrimitive from "recharts"
import { cn } from "@/lib/utils"

// shadcn's chart, trimmed to what the dashboard uses. Colors are plain CSS values (the
// dashboard's own tokens), set as --color-<key> on the container, so light and dark follow data-theme.
export type ChartConfig = Record<string, { label?: React.ReactNode; color?: string }>

const ChartContext = React.createContext<{ config: ChartConfig } | null>(null)

function useChart() {
  const context = React.useContext(ChartContext)
  if (!context) {
    throw new Error("useChart must be used within a <ChartContainer />")
  }
  return context
}

function ChartContainer({
  className,
  children,
  config,
  style,
  initialDimension = { width: 320, height: 200 },
  ...props
}: React.ComponentProps<"div"> & {
  config: ChartConfig
  children: React.ComponentProps<typeof RechartsPrimitive.ResponsiveContainer>["children"]
  initialDimension?: { width: number; height: number }
}) {
  const colors: Record<string, string> = {}
  for (const [key, item] of Object.entries(config)) {
    if (item.color) {
      colors[`--color-${key}`] = item.color
    }
  }
  return (
    <ChartContext.Provider value={{ config }}>
      <div
        data-slot="chart"
        className={cn(
          "flex justify-center text-xs [&_.recharts-cartesian-axis-tick-value]:fill-muted-foreground [&_.recharts-cartesian-grid_line]:stroke-border/60 [&_.recharts-rectangle.recharts-tooltip-cursor]:fill-accent [&_.recharts-surface]:overflow-visible [&_.recharts-layer]:outline-hidden [&_.recharts-surface]:outline-hidden",
          className
        )}
        style={{ ...colors, ...style } as React.CSSProperties}
        {...props}
      >
        <RechartsPrimitive.ResponsiveContainer initialDimension={initialDimension}>
          {children}
        </RechartsPrimitive.ResponsiveContainer>
      </div>
    </ChartContext.Provider>
  )
}

const ChartTooltip = RechartsPrimitive.Tooltip

interface ChartPayloadItem {
  dataKey?: string | number
  name?: string | number
  value?: number | string | null
  color?: string
  payload?: Record<string, unknown>
}

function ChartTooltipContent({
  active,
  payload,
  label,
  className,
  hideLabel = false,
  labelFormatter,
  formatter,
}: {
  active?: boolean
  payload?: ChartPayloadItem[]
  label?: React.ReactNode
  className?: string
  hideLabel?: boolean
  labelFormatter?: (label: React.ReactNode, payload: ChartPayloadItem[]) => React.ReactNode
  formatter?: (value: number | string, name: string, item: ChartPayloadItem) => React.ReactNode
}) {
  const { config } = useChart()
  const heading = labelFormatter ? labelFormatter(label, payload ?? []) : label
  const tooltip =
    active && payload?.length ? (
      <div className={cn("grid min-w-32 items-start gap-1.5 rounded-lg border bg-card px-2.5 py-1.5 text-xs shadow-xl", className)}>
        {!hideLabel && heading != null && <div className="font-medium">{heading}</div>}
        <div className="grid gap-1.5">
          {payload.map((item) => {
            const key = String(item.dataKey ?? item.name)
            const text = config[key]?.label ?? item.name
            const value = item.value ?? 0
            return (
              <div key={key} className="flex items-center gap-2">
                <span className="size-2.5 shrink-0 rounded-[2px]" style={{ background: item.color ?? `var(--color-${key})` }} />
                <span className="text-muted-foreground">{text}</span>
                <span className="mono ml-auto pl-3 font-medium text-foreground">{formatter ? formatter(value, key, item) : value}</span>
              </div>
            )
          })}
        </div>
      </div>
    ) : null
  return tooltip
}

const ChartLegend = RechartsPrimitive.Legend

function ChartLegendContent({
  className,
  payload,
}: {
  className?: string
  payload?: { dataKey?: unknown; value?: unknown; color?: string; type?: string }[]
}) {
  const { config } = useChart()
  const shown = (payload ?? []).filter((item) => item.type !== "none")
  return (
    <div className={cn("flex items-center justify-center gap-4 pt-2", className)}>
      {shown.map((item) => {
        const key = String(item.dataKey ?? item.value)
        return (
          <div key={key} className="flex items-center gap-1.5 text-muted-foreground">
            <span className="size-2 shrink-0 rounded-[2px]" style={{ background: item.color ?? `var(--color-${key})` }} />
            {config[key]?.label ?? String(item.value)}
          </div>
        )
      })}
    </div>
  )
}

export { ChartContainer, ChartTooltip, ChartTooltipContent, ChartLegend, ChartLegendContent }
