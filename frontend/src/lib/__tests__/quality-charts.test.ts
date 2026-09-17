import { describe, expect, it } from "vitest";

import {
  CHECK_COLOURS,
  QUALITY_CHARTS,
  countResult,
  mixColours,
  mixResult,
  qualityChartType,
  rateResult,
  topChecks,
  trendResult,
  worstFirst,
} from "@/lib/quality";

/** Two failing checks and one passing, deliberately out of order. */
const CHECKS = [
  { id: "a", name: "Duplicate key", passed: false, failed_rows: 120, failure_rate: 0.03 },
  { id: "b", name: "Too fast", passed: false, failed_rows: 480, failure_rate: 0.12 },
  { id: "c", name: "Age in range", passed: true, failed_rows: 0, failure_rate: 0 },
];

describe("which chart a quality panel draws", () => {
  it("draws what was chosen, where the view offers it", () => {
    expect(qualityChartType("rows", "donut")).toBe("donut");
    expect(qualityChartType("rate", "bar")).toBe("bar");
    expect(qualityChartType("trend", "area")).toBe("area");
  });

  it("falls back to the view's own chart where it does not", () => {
    // A donut of failure rates is not on the menu: rates are not parts of a
    // whole. A panel carrying that pair - saved as rows flagged, then moved to
    // rates - has to draw something, and it is the view's default.
    expect(qualityChartType("rate", "donut")).toBe("horizontal_bar");
    expect(qualityChartType("trend", "pie")).toBe("line");
  });

  it("draws what the panels built before this existed have always drawn", () => {
    expect(qualityChartType("rate", undefined)).toBe("horizontal_bar");
    expect(qualityChartType("rows", "")).toBe("horizontal_bar");
    expect(qualityChartType("trend", undefined)).toBe("line");
  });

  it("offers every view a chart, and every offer a real one", () => {
    for (const [view, offered] of Object.entries(QUALITY_CHARTS)) {
      expect(offered.length, `${view} offers nothing`).toBeGreaterThan(0);
      expect(new Set(offered.map((option) => option.value)).size).toBe(offered.length);
    }
  });
});

describe("which end of the chart the worst check lands on", () => {
  it("puts it last going across, where the axis is drawn bottom-up", () => {
    const names = worstFirst(CHECKS, (check) => check.failed_rows, true).map(
      (check) => check.name,
    );
    expect(names).toEqual(["Age in range", "Duplicate key", "Too fast"]);
  });

  it("puts it first going up, where the axis is drawn left to right", () => {
    const names = worstFirst(CHECKS, (check) => check.failed_rows, false).map(
      (check) => check.name,
    );
    expect(names).toEqual(["Too fast", "Duplicate key", "Age in range"]);
  });

  it("orders the results themselves the same way", () => {
    expect(countResult(CHECKS, false).rows[0]).toEqual(["Too fast", 480]);
    expect(countResult(CHECKS, true).rows[2]).toEqual(["Too fast", 480]);
    expect(rateResult(CHECKS, false).rows[0]).toEqual(["Too fast", 12]);
    expect(rateResult(CHECKS, true).rows[2]).toEqual(["Too fast", 12]);
  });
});

describe("the mix of passing, failing and never run", () => {
  const payload = { failing: 3, passing: 12, never_run: 1 };

  it("counts the three states, worst first", () => {
    expect(mixResult(payload).rows).toEqual([
      ["Failing", 3],
      ["Passing", 12],
      ["Never run", 1],
    ]);
  });

  it("turns them round for a horizontal bar, which reads bottom-up", () => {
    expect(mixResult(payload, true).rows).toEqual([
      ["Never run", 1],
      ["Passing", 12],
      ["Failing", 3],
    ]);
  });

  it("leaves out a state nothing is in", () => {
    const clean = { failing: 0, passing: 9, never_run: 0 };
    expect(mixResult(clean).rows).toEqual([["Passing", 9]]);
    expect(mixColours(clean)).toHaveLength(1);
  });

  it("keeps a colour against each state it drew, the same way round", () => {
    expect(mixColours(payload)).toHaveLength(mixResult(payload).rows.length);
    expect(mixColours(payload)[0]).toBe(CHECK_COLOURS.failing);
    expect(mixColours(payload, true)[0]).toBe(CHECK_COLOURS["not run"]);
  });
});

describe("cutting a panel to its worst few checks", () => {
  it("takes them worst first", () => {
    expect(topChecks(CHECKS, (check) => check.failed_rows, 2).map((c) => c.name)).toEqual([
      "Too fast",
      "Duplicate key",
    ]);
  });

  it("draws every check where no limit was set, or the limit covers them", () => {
    expect(topChecks(CHECKS, (check) => check.failed_rows, 0)).toBe(CHECKS);
    expect(topChecks(CHECKS, (check) => check.failed_rows, 3)).toBe(CHECKS);
    expect(topChecks(CHECKS, (check) => check.failed_rows, 99)).toBe(CHECKS);
  });
});

describe("a trend drawn from rates or from counts", () => {
  const history = {
    days: ["2026-09-08", "2026-09-09"],
    series: [{ id: "a", name: "Duplicate key", values: [4.1, 3.6], rows: [41, 36] }],
  };

  it("reads the rate by default, and the count when asked", () => {
    expect(trendResult(history).rows).toEqual([
      ["8 Sep", 4.1],
      ["9 Sep", 3.6],
    ]);
    expect(trendResult(history, "rows").rows).toEqual([
      ["8 Sep", 41],
      ["9 Sep", 36],
    ]);
  });

  it("keeps a day with no run as a gap rather than a nought", () => {
    const gapped = {
      days: ["2026-09-08", "2026-09-09"],
      series: [{ id: "a", name: "Duplicate key", values: [4.1, null], rows: [41, null] }],
    };
    expect(trendResult(gapped, "rows").rows[1]).toEqual(["9 Sep", null]);
  });
});

describe("a limit that is not a whole number of checks", () => {
  // A widget's settings can be written through the API as well as through the
  // dialog, and the dialog's own number input steps by one without a form to
  // enforce it. Half a check drawn as `slice(0, 0.5)` is no checks at all,
  // under a note calling them the worst 0 of 3.
  it("draws every check rather than none", () => {
    for (const limit of [0.5, 0.99, -3, Number.NaN]) {
      expect(
        topChecks(CHECKS, (check) => check.failed_rows, limit),
        `a limit of ${limit} emptied the chart`,
      ).toBe(CHECKS);
    }
  });

  it("rounds a fraction over one down to the checks it covers", () => {
    expect(
      topChecks(CHECKS, (check) => check.failed_rows, 2.7).map((c) => c.name),
    ).toEqual(["Too fast", "Duplicate key"]);
  });
});
