import { useEffect, useState } from "react";
import { Bar, BarChart, LabelList, XAxis, YAxis } from "recharts";
import { riseDelay } from "@/components/shared/rise";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { buildAppRows, chooseTimeUnit, formatAxisTick, type AppRow } from "@/lib/apps";
import { formatDuration } from "@/lib/format";
import { fetchJson } from "@/lib/http";
import { readStored, writeStored } from "@/lib/storage";
import type { AppsRange, AppsReply, AppUsage } from "@/lib/types";

const REFRESH_S = 60;
const STORAGE_KEY = "apps-range";
const ROW_HEIGHT_PX = 30;
const AXIS_HEIGHT_PX = 30;
const LEGEND_HEIGHT_PX = 28;
const RANGES: { range: AppsRange; label: string; empty: string }[] = [
  { range: "today", label: "Today", empty: "Nothing from the Mac yet today" },
  { range: "week", label: "This week", empty: "Nothing from the Mac yet this week" },
];

const CHART_CONFIG: ChartConfig = {
  youtube: { label: "YouTube", color: "var(--hot)" },
  sites: { label: "Other sites", color: "var(--muted)" },
  solid: { label: "Time", color: "var(--muted)" },
};

function readSavedRange(): AppsRange {
  const saved = readStored(STORAGE_KEY, "today");
  const range = saved === "week" ? "week" : "today";
  return range;
}

const TOTAL_CLASS = "mono fill-foreground text-[11px]";

function formatTotal(value: unknown): string {
  const text = formatDuration(Number(value));
  return text;
}

function AppsChart({ apps }: { apps: AppUsage[] }) {
  const unit = chooseTimeUnit(apps);
  const rows = buildAppRows(apps, unit);
  const hasBrowser = rows.some((row) => row.isBrowser);
  const height = rows.length * ROW_HEIGHT_PX + AXIS_HEIGHT_PX + (hasBrowser ? LEGEND_HEIGHT_PX : 0);
  return (
    <>
      <ChartContainer config={CHART_CONFIG} className="w-full" style={{ height }} role="img" aria-label="Time in front per Mac app">
        <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 56, bottom: 0, left: 0 }} barCategoryGap={6} accessibilityLayer={false}>
          <YAxis type="category" dataKey="label" width={92} tickLine={false} axisLine={false} interval={0} />
          <XAxis
            type="number"
            domain={[0, "auto"]}
            tickLine={false}
            axisLine={false}
            tickFormatter={(value: number) => formatAxisTick(value, unit)}
          />
          <ChartTooltip
            cursor={{ fill: "var(--line)" }}
            content={
              <ChartTooltipContent
                labelFormatter={(_label, payload) => String(payload[0]?.payload?.app ?? "")}
                formatter={(_value, _name, item) => formatDuration(readPieceSeconds(item.dataKey, item.payload as unknown as AppRow))}
              />
            }
          />
          {hasBrowser && <ChartLegend content={<ChartLegendContent />} />}
          <Bar dataKey="youtube" stackId="time" fill="var(--color-youtube)" isAnimationActive={false} legendType="square">
            <LabelList dataKey="youtubeEndSeconds" position="right" className={TOTAL_CLASS} formatter={formatTotal} />
          </Bar>
          <Bar dataKey="sites" stackId="time" fill="var(--color-sites)" isAnimationActive={false} legendType="square">
            <LabelList dataKey="sitesEndSeconds" position="right" className={TOTAL_CLASS} formatter={formatTotal} />
          </Bar>
          <Bar dataKey="solid" stackId="time" fill="var(--color-solid)" radius={3} isAnimationActive={false} legendType="none">
            <LabelList dataKey="totalSeconds" position="right" className={TOTAL_CLASS} formatter={formatTotal} />
          </Bar>
        </BarChart>
      </ChartContainer>
      <ul className="sr-only">
        {rows.map((row) => (
          <li key={row.app}>{`${row.app}, ${formatDuration(row.totalSeconds)}`}</li>
        ))}
      </ul>
    </>
  );
}

// The tooltip shows each piece's own exact time, not the axis unit's number.
export function readPieceSeconds(dataKey: string | number | undefined, row: AppRow): number {
  const seconds = dataKey === "youtube" ? row.youtubeSeconds : dataKey === "sites" ? row.sitesSeconds : row.totalSeconds;
  return seconds;
}

export function AppsCard({ now }: { now: number }) {
  const [range, setRange] = useState<AppsRange>(readSavedRange);
  const [loaded, setLoaded] = useState<{ range: AppsRange; apps: AppUsage[] } | null>(null);
  const refresh = Math.floor(now / REFRESH_S);

  useEffect(() => {
    let current = true;
    fetchJson<AppsReply>(`/api/apps?range=${range}`).then((reply) => {
      if (current) {
        setLoaded({ range, apps: reply?.apps ?? [] });
      }
    });
    return () => {
      current = false;
    };
  }, [range, refresh]);

  const pickRange = (next: AppsRange) => {
    setRange(next);
    writeStored(STORAGE_KEY, next);
  };
  const shown = loaded?.range === range ? loaded.apps : null;
  const empty = RANGES.find((entry) => entry.range === range)?.empty;

  return (
    <Card id="apps" className="card rise mt-4 gap-0 p-5" style={riseDelay(2)} aria-label="Apps">
      <div className="card-head">
        <div className="card-title">
          <h2 className="label">Apps</h2>
        </div>
        <div className="flex items-center gap-1" role="group" aria-label="Time range">
          {RANGES.map((entry) => (
            <Button key={entry.range} type="button" size="xs" variant={range === entry.range ? "secondary" : "ghost"} aria-pressed={range === entry.range} onClick={() => pickRange(entry.range)}>
              {entry.label}
            </Button>
          ))}
        </div>
      </div>
      {shown != null && shown.length > 0 && <AppsChart apps={shown} />}
      {shown != null && shown.length === 0 && <p className="muted py-6 text-center text-sm">{empty}</p>}
    </Card>
  );
}
