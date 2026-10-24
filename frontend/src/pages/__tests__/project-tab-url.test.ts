/**
 * Which tab a project opens on, read from the address.
 *
 * The tab is in the address so that a refresh, the back button and a pasted
 * link keep it. Anyone can type anything there, so it is read rather than
 * obeyed.
 *
 * The script was one of these tabs, called Command, until it moved to the
 * Scripts page. Links to it are still about - in bookmarks, in messages - and
 * they go on to the same script there.
 */
import { describe, expect, it } from "vitest";

import { scriptMovedTo, tabFromUrl } from "../ProjectDetail";

describe("the tab a link asks for", () => {
  it("carries the project's tabs", () => {
    expect(tabFromUrl("model")).toBe("model");
    expect(tabFromUrl("members")).toBe("members");
    expect(tabFromUrl("data")).toBe("data");
    expect(tabFromUrl("overview")).toBe("overview");
  });

  it("falls back to the project when the address says something else", () => {
    // A blank panel is worse than the page they asked for.
    expect(tabFromUrl(null)).toBe("overview");
    expect(tabFromUrl("")).toBe("overview");
    expect(tabFromUrl("nonsense")).toBe("overview");
    expect(tabFromUrl("SCRIPT")).toBe("overview");
  });

  it("is never the script, which is not a tab here any more", () => {
    expect(tabFromUrl("script")).toBe("overview");
  });
});

describe("a link to the old script tab", () => {
  it("goes on to the same project's script on the Scripts page", () => {
    expect(scriptMovedTo("script", "p-1")).toBe("/scripts?project=p-1");
  });

  it("leaves every other tab where it is", () => {
    expect(scriptMovedTo("model", "p-1")).toBeNull();
    expect(scriptMovedTo(null, "p-1")).toBeNull();
  });
});
