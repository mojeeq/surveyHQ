/**
 * Clicking a bar on a "tick all that apply" chart.
 *
 * Every other chart on a dashboard filters the page when a mark is clicked.
 * This one did nothing: its categories are columns of the file rather than
 * values of one variable, so the widget arrived with an empty `grouped_on`
 * and the click handler was never attached.
 *
 * What a click means here is "the rows that ticked this box", which is not an
 * equality against a value. A column can hold 1, "1" or "Yes" for the same
 * answer, so the filter asks the same question the bar was counted with.
 */
import { describe, expect, it } from "vitest";

import {
  clickedVariable,
  clickTarget,
  isClickable,
  ticked,
  withCrossFilter,
} from "../filters";

const empty = { op: "and" as const, conditions: [], groups: [] };

describe("a tick-all-that-apply chart", () => {
  const payload = {
    grouped_on: [],
    option_columns: { "Piped water": "water__1", "Well": "water__2" },
  };

  it("has no grouping variable, which is why the click was dropped", () => {
    expect(clickedVariable(payload)).toBe("");
  });

  it("offers the option columns instead, keyed by what is on the bar", () => {
    expect(ticked(payload)).toEqual({
      "Piped water": "water__1",
      Well: "water__2",
    });
  });

  it("is not mistaken for one on an ordinary chart", () => {
    expect(ticked({ grouped_on: ["province"] })).toBeUndefined();
    expect(ticked({ option_columns: {} })).toBeUndefined();
    expect(ticked(undefined)).toBeUndefined();
  });

  it("is clickable, and a click resolves to the option's own column", () => {
    // The line the original fault was on: the handler was attached only for a
    // chart with a grouping variable, so these charts never got one and a bar
    // did nothing at all.
    expect(isClickable(payload)).toBe(true);
    expect(clickTarget(payload, "Well")).toEqual({
      variable: "water__2",
      value: "Well",
      how: { operator: "selected", valueLabel: "Well" },
    });
  });

  it("resolves a bar whose label is not an option to nothing", () => {
    expect(clickTarget(payload, "Not an option")).toBeNull();
  });

  it("filters on the option's own column, asking whether it was ticked", () => {
    const filtered = withCrossFilter(empty, {
      variable: "water__2",
      value: "Well",
      valueLabel: "Well",
      label: "Water sources",
      from: "widget-1",
      operator: "selected",
    });
    expect(filtered.conditions).toEqual([
      {
        variable: "water__2",
        operator: "selected",
        value: null,
        use_label: false,
      },
    ]);
  });
});

describe("every other chart", () => {
  it("still resolves a click to its grouping variable", () => {
    const payload = { grouped_on: ["province"] };
    expect(isClickable(payload)).toBe(true);
    expect(clickTarget(payload, "Northern")).toEqual({
      variable: "province",
      value: "Northern",
    });
  });

  it("is not clickable where there is no category behind the mark", () => {
    expect(isClickable({ grouped_on: [] })).toBe(false);
    expect(clickTarget({ grouped_on: [] }, "anything")).toBeNull();
    expect(isClickable(undefined)).toBe(false);
  });

  it("still filters by the clicked value, against the label on the axis", () => {
    const filtered = withCrossFilter(empty, {
      variable: "province",
      value: "Northern",
      label: "Interviews by province",
      from: "widget-2",
    });
    expect(filtered.conditions).toEqual([
      {
        variable: "province",
        operator: "eq",
        value: "Northern",
        use_label: true,
      },
    ]);
  });

  it("keeps the filters the page already had", () => {
    const existing = {
      op: "and" as const,
      conditions: [
        { variable: "round", operator: "eq" as const, value: "2", use_label: false },
      ],
      groups: [],
    };
    const filtered = withCrossFilter(existing, {
      variable: "water__1",
      value: "Piped water",
      label: "Water sources",
      from: "widget-1",
      operator: "selected",
    });
    expect(filtered.conditions).toHaveLength(2);
    expect(filtered.conditions[0].variable).toBe("round");
  });
});
