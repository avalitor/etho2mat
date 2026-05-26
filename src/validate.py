"""Shared validation helpers and the loud, specific error types.

Philosophy (the inverse of the old ``try_or_default`` that swallowed everything):
validate up front and **refuse** with a message that names the file, the
location, and what was expected. Never silently default.

Two severities:
  * errors  -> raise; the run stops.
  * warnings -> printed via :func:`warn`; the run proceeds, final say is the user's.
"""

from __future__ import annotations

import sys


class Etho2matError(Exception):
    """Base class for every deliberate, user-facing failure."""


class InputError(Etho2matError):
    """A problem with something the user supplied (a file, a folder, a value)."""


class ConfigError(InputError):
    """A problem in one of the config CSVs (experiment_list / targets / mouse_map)."""


class ExcelError(InputError):
    """A problem with an Ethovision Excel export's structure or columns."""


class ArenaError(InputError):
    """Arena/hole detection produced an implausible or unconfirmed result."""


class SchemaError(Etho2matError):
    """The assembled record violates the frozen output contract."""


class CollisionError(InputError):
    """Two trials would write to the same output filename."""


def warn(message: str) -> None:
    """Print a non-blocking warning to stderr, clearly marked."""
    print(f"  !!  WARNING: {message}", file=sys.stderr)


def require(condition: bool, error: Etho2matError) -> None:
    """Raise ``error`` unless ``condition`` holds. Keeps call sites terse."""
    if not condition:
        raise error
