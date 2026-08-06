"""Durable state for the Scheduler control plane.

`SchedulerStore` is the interface; `SQLiteStore` is the only implementation today.
See specs/scheduler-persistence.md for what is stored, what deliberately is not,
and why the SQLite file on a free-tier container is not the durability an operator
who needs durability should rely on.
"""

from scheduler.persistence.sqlite_store import SQLiteStore
from scheduler.persistence.store import SchedulerStore

__all__ = ["SQLiteStore", "SchedulerStore"]
