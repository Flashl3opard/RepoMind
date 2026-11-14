"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { BenchmarkModeSummary } from "@/lib/api";

const MODE_COLORS: Record<string, string> = {
  full: "var(--color-primary)",
  diff_only: "var(--color-muted-foreground)",
  naive: "var(--color-warning)",
};

const MODE_LABELS: Record<string, string> = {
  full: "full",
  diff_only: "diff_only",
  naive: "naive",
};

export function BenchmarkChart({
  summary,
}: {
  summary: Record<string, BenchmarkModeSummary>;
}) {
  const modes = Object.keys(summary);

  const data = [
    {
      metric: "Recall (positives)",
      ...Object.fromEntries(
        modes.map((mode) => [mode, toPercent(summary[mode].recall)]),
      ),
    },
    {
      metric: "False-positive rate (negatives)",
      ...Object.fromEntries(
        modes.map((mode) => [
          mode,
          toPercent(summary[mode].false_positive_rate),
        ]),
      ),
    },
  ];

  return (
    <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="metric" tick={{ fontSize: 12 }} />
          <YAxis unit="%" tick={{ fontSize: 12 }} />
          <Tooltip formatter={(value) => `${Number(value).toFixed(1)}%`} />
          <Legend />
          {modes.map((mode) => (
            <Bar
              key={mode}
              dataKey={mode}
              name={MODE_LABELS[mode] ?? mode}
              fill={MODE_COLORS[mode] ?? "var(--color-secondary)"}
              radius={[4, 4, 0, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function toPercent(value: number | null): number {
  return value == null ? 0 : value * 100;
}
