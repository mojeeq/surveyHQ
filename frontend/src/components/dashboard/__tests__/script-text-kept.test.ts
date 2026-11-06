/**
 * Whether the editor says the text is missing.
 *
 * A run from before the text of a run was recorded left its time, reads and
 * writes and no text, and the editor asked only about text: it opened on an
 * empty box and said nothing about why, so a script the page listed could
 * not be read and looked broken.
 */
import { describe, expect, it } from "vitest";

import { textNotKept } from "../../ProjectScript";

const ran = "2026-10-08T09:00:00Z";

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

  it("does not for a script that has never run", () => {
    expect(textNotKept({ text: "", unsaved_run: "", last_run_at: null })).toBe(false);
  });

  it("counts saved spaces as no text", () => {
    expect(textNotKept({ text: "  \n", unsaved_run: "", last_run_at: ran })).toBe(true);
  });
});
