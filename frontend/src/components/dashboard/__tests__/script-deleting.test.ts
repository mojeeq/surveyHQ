/**
 * Whether the editor offers Delete, and whether it says the text is missing.
 *
 * The Scripts page lists every project whose script has run. A run from
 * before the text of a run was recorded left its time, reads and writes and
 * no text, and the editor asked only about text: it opened on an empty box,
 * said nothing about why, and showed no Delete - so a script the page listed
 * could be neither read nor removed.
 */
import { describe, expect, it } from "vitest";

import { hasScript, textNotKept } from "../../ProjectScript";

const ran = "2026-10-08T09:00:00Z";

describe("whether there is a script to delete", () => {
  it("is yes for a run with no text, which is what the page lists", () => {
    expect(hasScript({ text: "", unsaved_run: "", last_run_at: ran })).toBe(true);
  });

  it("is yes for a saved script that has never run", () => {
    expect(hasScript({ text: "use people", unsaved_run: "", last_run_at: null })).toBe(true);
  });

  it("is yes for a draft that was tried and refused", () => {
    expect(hasScript({ text: "", unsaved_run: "* comments", last_run_at: null })).toBe(true);
  });

  it("is no for a project nobody has written or run anything in", () => {
    expect(hasScript({ text: "", unsaved_run: "", last_run_at: null })).toBe(false);
  });
});

describe("whether the editor says the text was not kept", () => {
  it("says so for a run with nothing of its text", () => {
    expect(textNotKept({ text: "", unsaved_run: "", last_run_at: ran })).toBe(true);
  });

  it("does not for a run whose text was kept", () => {
    expect(textNotKept({ text: "", unsaved_run: "use people", last_run_at: ran })).toBe(false);
  });

  it("does not for a saved script", () => {
    expect(textNotKept({ text: "use people", unsaved_run: "", last_run_at: ran })).toBe(false);
  });

  it("does not for a project that has never run", () => {
    expect(textNotKept({ text: "", unsaved_run: "", last_run_at: null })).toBe(false);
  });

  it("counts saved spaces as no text", () => {
    expect(textNotKept({ text: "  \n", unsaved_run: "", last_run_at: ran })).toBe(true);
  });
});
