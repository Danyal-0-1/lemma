# ─────────────────────────────────────────────────────────────────────────────
# coordinator.py — the bridge from an approved Spec to a live build workspace.
# READING ORDER: backend #35
#
# WHAT THIS FILE DOES: builds a workspace from a Spec artifact (via WorkspaceManager)
# and announces it — workspace_created (so the sidebar shows it) and phase_changed to
# "build" (so the UI switches to the review tabs).
#
# WHY it's separate from the manager: the manager knows about directories and git; the
# coordinator knows about the app's phases and events. Keeping "make the folder" apart
# from "tell the UI" mirrors the same separation the ideation side uses.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import logging

from app.events import event_bus
from app.models import Workspace
from app.workspaces import manager

logger = logging.getLogger("aicompany.build")


async def build_from_spec(spec_artifact_id: int) -> Workspace:
    """Create a workspace from a Spec, then emit workspace_created + phase_changed(build).

    Exists as the single "start building this" action the REST layer calls. The heavy
    work (filesystem + git) runs off the event loop via asyncio.to_thread.
    """
    workspace = await asyncio.to_thread(manager.create_from_spec, spec_artifact_id)

    event_bus.publish(
        "workspace_created",
        {"workspace_id": workspace.id, "path": workspace.path, "slug": workspace.slug},
    )
    event_bus.publish("phase_changed", {"phase": "build"})
    return workspace
