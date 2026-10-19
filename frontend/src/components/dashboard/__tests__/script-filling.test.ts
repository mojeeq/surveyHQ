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
 * saved that follows a newer one.
 *
 * Two things make that harder than it sounds, and both have been got wrong.
 *
 * "From the moment they change it" has to be measured against what the editor
 * last put in the box, not against what is saved. A project with nothing
 * saved and a run on record opens on the run, so the box differs from the
 * saved text with nobody having touched anything.
 *
 * And opening is not following. An opening box falls back to the last run so
 * that a project whose data was plainly built by something does not open
 * blank; an open one must not, or clearing the box and saving it hands the
 * run back.
 */
import { describe, expect, it } from "vitest";

import { fillWith } from "../../ProjectScript";

/** Open on p1, with the box as the editor left it: untouched.
 *
 *  `knownRun` is the run the editor last settled on, which is the other half
 *  of "has anything happened" - so a test that means "nothing has changed"
 *  has to pass the answer's own run here, and one that means "somebody ran
 *  something" passes the older one. */
const untouched = (shown: string, saved: string, knownRun = "") => ({
  filled: "p1",
  project: "p1",
  inBox: shown,
  shown,
  saved,
  knownRun,
});

/** Open on p1, with something else in the box: the person typed. */
const typed = (inBox: string, shown: string, saved: string, knownRun = "") => ({
  filled: "p1",
  project: "p1",
  inBox,
  shown,
  saved,
  knownRun,
});

describe("what fills the editor's box", () => {
  describe("opening on a project", () => {
    const opening = {
      filled: null,
      project: "p1",
      inBox: "",
      shown: "",
      saved: "",
      knownRun: "",
    };

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
          {
            filled: "p1",
            project: "p2",
            inBox: "half a draft",
            shown: "",
            saved: "",
            knownRun: "",
          },
        ),
      ).toBe("p2's script");
    });
  });

  describe("an untouched box", () => {
    it("follows a script saved somewhere else", () => {
      // A colleague saved while the tab was shut, and the stale cached answer
      // was being treated as the last word.
      expect(fillWith({ text: "theirs", unsaved_run: "" }, untouched("mine", "mine"))).toBe(
        "theirs",
      );
    });

    it("follows one even while it holds a run nobody has touched", () => {
      // Nothing saved, a run on record, so the box opened on the run and
      // differs from the saved text with nobody having touched it. Reading
      // that as an edit left the box ignoring this answer and Save then
      // overwrote the colleague - the whole point of the rule, lost to the
      // one case that looks like a draft and is not.
      expect(fillWith({ text: "theirs", unsaved_run: "what ran" }, untouched("what ran", ""))).toBe(
        "theirs",
      );
    });

    it("follows a newer recorded run on a project with nothing saved", () => {
      // Two people in one project, no delete and no failure needed. The box
      // opened on the run, nobody has touched it, and somebody else ran
      // something: the server records the newer run and the saved text is
      // empty either way.
      //
      // Comparing only the saved text made these two indistinguishable, so
      // the box kept the old run and neither notice offered the new one - the
      // amber one wants the run already in the box, the offer wants a saved
      // script.
      expect(fillWith({ text: "", unsaved_run: "B" }, untouched("A", "", "A"))).toBe("B");
    });

    it("follows a colleague's save even when a run is on record behind it", () => {
      expect(fillWith({ text: "theirs", unsaved_run: "B" }, untouched("A", "", "A"))).toBe(
        "theirs",
      );
    });

    it("shows the run when a colleague deleted the script out from under it", () => {
      // Nothing saved any more, but the run is still on record, which is what
      // this project now opens on. Following the saved text alone would empty
      // a box nobody had touched and say nothing about why.
      expect(fillWith({ text: "", unsaved_run: "what ran" }, untouched("kept", "kept"))).toBe(
        "what ran",
      );
    });

    it("is left alone when nothing has been saved since", () => {
      // The plain refetch on that same project. Writing the saved text over
      // the box would empty it every time the query came back.
      expect(
        fillWith({ text: "", unsaved_run: "what ran" }, untouched("what ran", "", "what ran")),
      ).toBe(null);
    });

    it("does not take the last run back after it was cleared and saved", () => {
      // Saved empty on purpose, and the run on record is the one that was
      // there when they saved - so nothing has happened and the thing they
      // just replaced with nothing is not handed back.
      expect(fillWith({ text: "", unsaved_run: "what ran" }, untouched("", "", "what ran"))).toBe(
        null,
      );
    });

    it("follows a run that happened after the box was cleared and saved", () => {
      // The same empty box, and this time somebody has run something since.
      // That is a new thing to say, not the clear being undone - and nothing
      // else would say it, the amber notice wanting the run in the box and
      // the offer wanting a saved script.
      expect(fillWith({ text: "", unsaved_run: "newer" }, untouched("", "", "what ran"))).toBe(
        "newer",
      );
    });

    it("brings the script back when a delete failed", () => {
      // Asking for a delete empties the box, the saved text and the cached
      // answer, all three with the request. A delete that fails puts the
      // answer back, and then this is what returns the script to an untouched
      // box - no rollback of its own to write.
      //
      // Which makes the cached answer load-bearing in the other direction
      // too: leave it holding the script while the delete is in flight and
      // this same line fires immediately, undoing the clear and showing the
      // script being deleted for as long as the request takes. `fillWith`
      // cannot tell those two apart - only what the cache holds can - so it
      // is `script-box-guard.mjs` that keeps the emptying beside the request.
      expect(fillWith({ text: "the old script", unsaved_run: "" }, untouched("", ""))).toBe(
        "the old script",
      );
    });

    it("cannot reach a run from an emptied box, which is why a failed delete reopens", () => {
      // An empty box showing an empty saved text. Following leaves it alone,
      // which is right when somebody cleared the box and saved it on purpose
      // and wrong after a delete that failed, where the run was on screen a
      // moment ago and would now be invisible with no notice and no offer.
      //
      // From here the two are the same question, so nothing in this function
      // can tell them apart - note that this is the emptied box specifically:
      // a box still showing a run does follow a newer one, above. The
      // delete's failure path marks the project unfilled instead, which sends
      // the next pass down the opening branch below.
      expect(fillWith({ text: "", unsaved_run: "what ran" }, untouched("", "", "what ran"))).toBe(
        null,
      );
      expect(
        fillWith(
          { text: "", unsaved_run: "what ran" },
          { filled: null, project: "p1", inBox: "", shown: "", saved: "", knownRun: "what ran" },
        ),
      ).toBe("what ran");
    });

    it("stays empty while a delete is in flight", () => {
      // The cached answer was emptied with the request, so there is nothing
      // newer than the empty saved text and nothing refills the box.
      expect(fillWith({ text: "", unsaved_run: "" }, untouched("", ""))).toBe(null);
    });

    it("needs no write when a colleague saves exactly the run on show", () => {
      // The answer moves a long way - from a run with nothing saved to a
      // saved script and no run - and the text to show is the same either
      // way, so there is nothing to put in the box.
      //
      // Which is all this function says. It does not say nothing happened,
      // and the editor must still settle the saved text and the run, or Save
      // goes on claiming unsaved changes for a box that matches the server
      // and then switches off entirely when the box is cleared. That part is
      // the effect's and `script-box-guard.mjs` holds it.
      expect(fillWith({ text: "A", unsaved_run: "" }, untouched("A", "", "A"))).toBe(null);
    });

    it("is left alone when the answer says what the box already shows", () => {
      expect(fillWith({ text: "use people", unsaved_run: "" }, untouched("use people", "use people"))).toBe(
        null,
      );
    });
  });

  describe("a box somebody has changed", () => {
    it("is left alone mid-draft", () => {
      // The failed-run case: the run refetches for the newer complaint, and
      // the draft being corrected has to survive it.
      expect(
        fillWith({ text: "use people", unsaved_run: "" }, typed("use peopl", "use people", "use people")),
      ).toBe(null);
    });

    it("is left alone when they cleared it and have not saved", () => {
      // Selecting all and deleting is a change, and Save is live for it.
      expect(fillWith({ text: "use people", unsaved_run: "" }, typed("", "use people", "use people"))).toBe(
        null,
      );
    });

    it("is left alone when they asked for the recorded run back", () => {
      // "Put it in the box" is the person acting, not the editor filling.
      expect(
        fillWith({ text: "kept", unsaved_run: "tried" }, typed("tried", "kept", "kept")),
      ).toBe(null);
    });

    it("is left alone even when somebody else has saved since", () => {
      // Their draft outranks a newer script, because losing a draft is silent
      // and losing the race on Save is not. The lost update that leaves is a
      // version on the record and a refusal on PUT, not a textarea rule.
      expect(fillWith({ text: "theirs", unsaved_run: "" }, typed("mine", "was", "was"))).toBe(null);
    });
  });
});
