// Pure severity/risk ordering helpers shared by FindingCard, the findings list, and
// badges. No I/O.
import type { FindingResponse } from "./types";

export const SEVERITY_ORDER = ["error", "warning", "info"] as const;
export type Severity = (typeof SEVERITY_ORDER)[number];

const SEVERITY_RANK: Record<Severity, number> = {
  error: 0,
  warning: 1,
  info: 2,
};

export function severityRank(severity: string): number {
  return SEVERITY_RANK[severity as Severity] ?? SEVERITY_ORDER.length;
}

/** Most severe first; stable (equal-severity items keep their relative order). */
export function sortBySeverity<T extends { severity: string }>(
  items: T[],
): T[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const rankDiff =
        severityRank(a.item.severity) - severityRank(b.item.severity);
      return rankDiff !== 0 ? rankDiff : a.index - b.index;
    })
    .map(({ item }) => item);
}

/** Groups findings by file, each file's findings sorted most-severe-first. */
export function groupFindingsByFile(
  findings: FindingResponse[],
): { file: string; findings: FindingResponse[] }[] {
  const byFile = new Map<string, FindingResponse[]>();
  for (const finding of findings) {
    const existing = byFile.get(finding.file);
    if (existing) {
      existing.push(finding);
    } else {
      byFile.set(finding.file, [finding]);
    }
  }
  return Array.from(byFile.entries()).map(([file, fileFindings]) => ({
    file,
    findings: sortBySeverity(fileFindings),
  }));
}

export const RISK_ORDER = ["high", "medium", "low"] as const;

export function riskRank(risk: string): number {
  const index = RISK_ORDER.indexOf(risk as (typeof RISK_ORDER)[number]);
  return index === -1 ? RISK_ORDER.length : index;
}
