/**
 * Which script the editor opens on.
 *
 * Running and saving are separate here: a script is tried before it is kept.
 * So a project can have a saved script, a run that was never saved, both, or
 * neither, and the box has to choose. It has chosen wrong twice - once
 * preferring the saved text so hard that a recorded run could not be reached
 * at all, and once treating a box of spaces as a script - so the choice lives
 * in a function of its own now.
 */
import { describe, expect, it } from "vitest";

import { openingText } from "../../ProjectScript";

describe("the text the editor opens on", () => {
  it("is the saved script when there is one", () => {
    expect(openingText({ text: "use people", unsaved_run: "" })).toBe("use people");
  });

  it("is the last run when nothing was saved", () => {
    // The complaint this started from: a blank box on a project whose data
    // was plainly built by something.
    expect(openingText({ text: "", unsaved_run: "use people\ngen a = 1" })).toBe(
      "use people\ngen a = 1",
    );
  });

  it("is the saved script when both exist, not the experiment", () => {
    // They are different things. Opening on the run would let something
    // somebody tried take the place of something they kept - and Run would
    // then run the experiment. The run is a click away instead.
    expect(openingText({ text: "kept", unsaved_run: "tried" })).toBe("kept");
  });

  it("does not count a box of spaces as a saved script", () => {
    expect(openingText({ text: "   \n  \n", unsaved_run: "use people" })).toBe(
      "use people",
    );
  });

  it("is empty when there is nothing of either", () => {
    expect(openingText({ text: "", unsaved_run: "" })).toBe("");
  });
});
