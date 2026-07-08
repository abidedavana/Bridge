"""Bridge dashboard: a thin FastAPI app + one static page over a run's RunState.

The demo money shots, in priority order: the pass-rate-per-iteration chart, the
current primary diagnostic, the token/cost counter, and the endpoint badge
proving where the brain runs. It reads the run-state JSON written by the loop;
it has no other coupling to the rest of Bridge.
"""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
