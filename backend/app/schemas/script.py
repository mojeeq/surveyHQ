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
    lines: int = 0
    last_run_at: dt.datetime | None = None
    last_error: str = ""


class ScriptsOverview(BaseModel):
    places: list[ScriptPlace] = Field(default_factory=list)
