import { describe, expect, it } from "vitest";

import {
  QUALITY_CHARTS,
  countResult,
  qualityChartType,
  rateResult,
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
