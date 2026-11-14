import { describe, expect, it } from "vitest";
import {
  groupFindingsByFile,
  riskRank,
  severityRank,
  sortBySeverity,
} from "./severity";
import type { FindingResponse } from "./types";

function finding(overrides: Partial<FindingResponse> = {}): FindingResponse {
  return {
    file: "a.py",
    start_line: 1,
    end_line: 2,
    severity: "info",
    category: "style",
    message: "msg",
    evidence: [],
    ...overrides,
  };
}

describe("severityRank", () => {
  it("ranks error highest, then warning, then info", () => {
    expect(severityRank("error")).toBeLessThan(severityRank("warning"));
    expect(severityRank("warning")).toBeLessThan(severityRank("info"));
  });

  it("ranks unknown severities last", () => {
    expect(severityRank("unknown")).toBeGreaterThan(severityRank("info"));
  });
});

describe("sortBySeverity", () => {
  it("sorts most severe first", () => {
    const items = [
      finding({ severity: "info" }),
      finding({ severity: "error" }),
      finding({ severity: "warning" }),
    ];
    const sorted = sortBySeverity(items);
    expect(sorted.map((f) => f.severity)).toEqual(["error", "warning", "info"]);
  });

  it("preserves relative order for equal severities (stable sort)", () => {
    const items = [
      finding({ severity: "warning", message: "first" }),
      finding({ severity: "warning", message: "second" }),
    ];
    const sorted = sortBySeverity(items);
    expect(sorted.map((f) => f.message)).toEqual(["first", "second"]);
  });

  it("does not mutate the input array", () => {
    const items = [
      finding({ severity: "info" }),
      finding({ severity: "error" }),
    ];
    const original = [...items];
    sortBySeverity(items);
    expect(items).toEqual(original);
  });
});

describe("groupFindingsByFile", () => {
  it("groups findings by file", () => {
    const items = [
      finding({ file: "a.py" }),
      finding({ file: "b.py" }),
      finding({ file: "a.py" }),
    ];
    const grouped = groupFindingsByFile(items);
    expect(grouped.map((g) => g.file)).toEqual(["a.py", "b.py"]);
    expect(grouped[0].findings).toHaveLength(2);
    expect(grouped[1].findings).toHaveLength(1);
  });

  it("sorts each file's findings by severity", () => {
    const items = [
      finding({ file: "a.py", severity: "info", message: "low" }),
      finding({ file: "a.py", severity: "error", message: "high" }),
    ];
    const grouped = groupFindingsByFile(items);
    expect(grouped[0].findings.map((f) => f.message)).toEqual(["high", "low"]);
  });

  it("returns an empty list for no findings", () => {
    expect(groupFindingsByFile([])).toEqual([]);
  });
});

describe("riskRank", () => {
  it("ranks high lowest (most severe first)", () => {
    expect(riskRank("high")).toBeLessThan(riskRank("medium"));
    expect(riskRank("medium")).toBeLessThan(riskRank("low"));
  });

  it("ranks unknown risk levels last", () => {
    expect(riskRank("unknown")).toBeGreaterThan(riskRank("low"));
  });
});
