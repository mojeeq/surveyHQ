/**
 * The bar a top-N display invents.
 *
 * Past the cut, a chart folds the rest into one "Other (5)". It stands for
 * several categories and is not any of them, so filtering by it asks for rows
 * whose value is literally "Other (5)". There are none: every widget on the
 * page empties at once, and nothing says why.
 *
 * That was already true of ordinary charts before tick-all-that-apply charts
 * became clickable at all. A click on such a bar is ignored now, on every
 * chart, rather than answered with a filter that matches nothing.
 */
import { describe, expect, it } from "vitest";

import { isFoldedBar } from "../../ChartCard";
import type { QueryResult } from "@/lib/types";

const result = (categories: string[]): QueryResult =>
  ({
    columns: [
      { name: "g", label: "Group", type: "dimension", data_type: "text" },
      { name: "n", label: "Count", type: "measure", data_type: "number" },
    ],
    rows: categories.map((name, index) => [name, index + 1]),
    row_count: categories.length,
    truncated: false,
    sql: "",
    duration_ms: 0,
  }) as unknown as QueryResult;

describe("a folded top-N bar", () => {
  it("is recognised when no row carries that name", () => {
    expect(isFoldedBar(result(["North", "South"]), "Other (5)")).toBe(true);
  });

  it("is not claimed for a real category that happens to be called that", () => {
    // Checked against the rows rather than by the shape of the name, so a
    // category genuinely labelled "Other (3)" still filters.
    expect(isFoldedBar(result(["North", "Other (3)"]), "Other (3)")).toBe(false);
  });

  it("leaves every ordinary category alone", () => {
    expect(isFoldedBar(result(["North", "South"]), "North")).toBe(false);
    expect(isFoldedBar(result(["North"]), "Other")).toBe(false);
    expect(isFoldedBar(result(["North"]), "Others (2)")).toBe(false);
  });

  it("says nothing about a result with no category column", () => {
    const measures = {
      columns: [{ name: "n", label: "Count", type: "measure", data_type: "number" }],
      rows: [[1]],
      row_count: 1,
      truncated: false,
      sql: "",
      duration_ms: 0,
    } as unknown as QueryResult;
    expect(isFoldedBar(measures, "Other (5)")).toBe(false);
  });
});
