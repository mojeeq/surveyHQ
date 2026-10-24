/**
 * Which tab a project opens on, read from the address.
 *
 * The Scripts page lists every project's script and had nowhere to send you:
 * its cards pointed at the project, which opens on Data, leaving the reader
 * to notice a tab called Command. So the tab is in the address now, and the
 * cards link straight to the script.
 *
 * Which puts a permission question in the address too. The script tab is only
 * offered to somebody who may change the data, because running it does, so a
 * link asking for it has to be read rather than obeyed.
 */
import { describe, expect, it } from "vitest";

import { tabFromUrl } from "../ProjectDetail";

describe("the tab a link asks for", () => {
  it("opens the script for somebody who may change the data", () => {
    expect(tabFromUrl("script", true)).toBe("script");
  });

  it("opens the project instead for somebody who may not", () => {
    // Not an error page: they can see the project, just not that tab. The
    // server refuses the save and the run as well; this is so that nothing
    // invites them to try.
    expect(tabFromUrl("script", false)).toBe("overview");
  });

  it("carries the other tabs for anybody", () => {
    expect(tabFromUrl("model", false)).toBe("model");
    expect(tabFromUrl("members", false)).toBe("members");
    expect(tabFromUrl("data", false)).toBe("data");
    expect(tabFromUrl("overview", false)).toBe("overview");
  });

  it("falls back to the project when the address says something else", () => {
    // Anyone can type anything in there, and a blank panel is worse than the
    // page they asked for.
    expect(tabFromUrl(null, true)).toBe("overview");
    expect(tabFromUrl("", true)).toBe("overview");
    expect(tabFromUrl("nonsense", true)).toBe("overview");
    expect(tabFromUrl("SCRIPT", true)).toBe("overview");
  });
});
