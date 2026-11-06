"""Beat intervals that are read when beat asks, not when beat started.

The scheduler is handed its intervals once, at start-up, which is why
changing how often fieldwork is looked at used to mean restarting the
containers. A schedule is only asked two things - how often, and is it due -
so an interval that answers the first from the settings store rather than
from a number captured at import makes the rest of it work without a
restart.

Celery's own documentation is explicit that this is how a run-time schedule
change is done, and that how quickly it takes hold is decided by
`beat_max_loop_interval`: beat sleeps until the next run is due, so a
schedule shortened from an hour to five minutes is not noticed until beat
next wakes. That is set to a minute beside this, which is the price of the
whole arrangement: a minute, once, after a change.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from celery.schedules import schedule


class Tunable(schedule):
    """Every N minutes, where N is whatever the setting says right now."""

    def __init__(self, name: str) -> None:
        self.name = name
        # Celery's own __init__ assigns run_every, which the property below
        # ignores; the argument is here to satisfy it rather than to be used.
        super().__init__(run_every=60.0)

    @property
    def run_every(self) -> dt.timedelta:  # type: ignore[override]
        from app.services import preferences

        try:
            minutes = max(1, int(preferences.value(self.name)))
        except Exception:  # noqa: BLE001 - a schedule must not stop the scheduler
            minutes = 15
        return dt.timedelta(minutes=minutes)

    @run_every.setter
    def run_every(self, value: Any) -> None:
        """Ignored: the setting is the interval, and nothing else may set it."""

    def __repr__(self) -> str:
        return f"<tunable: {self.name} = {self.run_every}>"

    def __reduce__(self) -> tuple[Any, ...]:
        # Beat writes its schedule to disk between runs, and what comes back
        # has to be this again rather than a plain interval frozen at the
        # moment it was written.
        return self.__class__, (self.name,)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Tunable):
            return self.name == other.name
        return NotImplemented

    def __hash__(self) -> int:
        return hash((type(self).__name__, self.name))
