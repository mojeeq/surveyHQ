"""What the scripts overview sends to the page."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class ScriptPlace(BaseModel):
    """One project's script, and where it sits in the order."""

    project_id: str
    project_name: str
    # How many scripts have to have run before this one can. Every script at
    # step 0 can run at once; nothing about the number is a position in a
    # queue.
    step: int = 0
    # The scripts immediately above this one, by project name, which is what
    # makes the step mean anything.
    waits_for: list[str] = Field(default_factory=list)
    # This script reads what another writes, which reads what this one writes.
    # There is no order then, and the page says so rather than inventing one.
    in_a_cycle: bool = False
    # By name rather than by id: whoever reads this is looking at a page.
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    # Counted from the saved script, or from what last ran where nothing is
    # saved: a run that was never kept is still a script of some length, and
    # saying "run without being saved" for it read as "there is nothing here".
    lines: int = 0
    # Where this sits among the scripts it shares a step with, so the page can
    # send the step back in order when somebody moves one.
    rank: int = 0
    # Whether what `lines` counted is the saved script. False means it is the
    # last run, which the card says and the editor opens on.
    saved: bool = True
    last_run_at: dt.datetime | None = None
    last_error: str = ""
    # Whether this reader may change this script, which is not the same as
    # being able to see it: the page lists every project somebody can view,
    # and most of those they cannot edit. Said here so the page can offer the
    # way in only where there is one, rather than showing everybody a button
    # that quietly puts them back on the project.
    can_edit: bool = False


class ScriptsOverview(BaseModel):
    places: list[ScriptPlace] = Field(default_factory=list)


class ScriptOrderIn(BaseModel):
    """The order somebody wants for scripts that share a step.

    The whole step, in the order it should read. A partial list would leave
    the rest somewhere undefined, and the page always has the whole step in
    front of it when somebody moves a card.
    """

    project_ids: list[str] = Field(default_factory=list)
