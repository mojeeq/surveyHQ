/**
 * What an answer from the server puts in the editor's box.
 *
 * There are two ways to get this wrong and they pull against each other. A
 * box that follows the query throws away the draft somebody is in the middle
 * of correcting - which is what a failed run does, since it refetches to show
 * the newer complaint. A box filled once and then left alone hides a script a
 * colleague saved while the tab was shut, and Save afterwards writes over
 * their work with neither of them seeing it.
 *
 * Both have happened. The rule that holds both ends: the box is the person's
 * from the moment they change it, and until then it is a view of what is
 * saved that a newer answer may follow.
 *
 * Opening and following are not the same rule, which is the third thing that
 * went wrong here. An opening box falls back to the last run so that a
 * project whose data was plainly built by something does not open blank. An
 * open one must not, or clearing the box and saving it puts the run back.
 */
import { describe, expect, it } from "vitest";

import { fillWith } from "../../ProjectScript";

/** Already open on p1, and these are the parts that vary. */
const open = (inBox: string, saved: string) => ({
  filled: "p1",
  project: "p1",
  inBox,
  saved,
});

describe("what fills the editor's box", () => {
  describe("opening on a project", () => {
    const opening = { filled: null, project: "p1", inBox: "", saved: "" };

    it("is the saved script", () => {
      expect(fillWith({ text: "use people", unsaved_run: "" }, opening)).toBe("use people");
    });

    it("falls back to what ran when nothing is saved", () => {
      expect(fillWith({ text: "", unsaved_run: "what ran" }, opening)).toBe("what ran");
    });

    it("happens on a project change whatever is in the box", () => {
      // Without this an untouched box would be judged against the previous
      // project's saved text, and a draft left in one project would turn up
      // in the next one's editor as though it belonged there.
      expect(
        fillWith(
          { text: "p2's script", unsaved_run: "" },
          { filled: "p1", project: "p2", inBox: "half a draft", saved: "" },
        ),
      ).toBe("p2's script");
    });
  });

  describe("an open box nobody has changed", () => {
    it("follows a script saved somewhere else", () => {
      // The finding: a colleague saved while the tab was shut, and the stale
      // cached answer was treated as the last word.
      expect(fillWith({ text: "theirs", unsaved_run: "" }, open("mine", "mine"))).toBe(
        "theirs",
      );
    });

    it("does not take the last run back off the server", () => {
      // Somebody cleared the box and saved it. The box is empty and matches
      // what is saved, so it follows - and following `openingText` here would
      // hand back the run they had just finished replacing with nothing.
      expect(fillWith({ text: "", unsaved_run: "what ran" }, open("", ""))).toBe("");
    });

    it("empties when the script was deleted", () => {
      expect(fillWith({ text: "", unsaved_run: "" }, open("gone", "gone"))).toBe("");
    });
  });

  describe("a box somebody has changed", () => {
    it("is left alone mid-draft", () => {
      // The failed-run case: the run refetches for the newer complaint, and
      // the draft being corrected has to survive it.
      expect(fillWith({ text: "use people", unsaved_run: "" }, open("use peopl", "use people"))).toBe(
        null,
      );
    });

    it("is left alone when it holds a run got back", () => {
      // Nothing saved, something ran: the box opened on the run and so is
      // dirty. Untouched by the person, but not a view of anything saved, and
      // following would empty the box that was just filled on purpose.
      expect(fillWith({ text: "", unsaved_run: "what ran" }, open("what ran", ""))).toBe(null);
    });

    it("is left alone when they cleared it and have not saved", () => {
      // Selecting all and deleting is a change, and Save is live for it.
      expect(fillWith({ text: "use people", unsaved_run: "" }, open("", "use people"))).toBe(
        null,
      );
    });
  });
});
