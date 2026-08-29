"""Surface-layer abstraction over a harness's tool inventory.

Every harness exposes a set of callable tools — the model's *surface*.  The
same model behind two different tool sets is a different product, so the
surface itself is first-class data that can be inspected, selected, and packed
into reproducible task bundles.

This module does not call out to any external service; it is pure data
structures and a thin registry that deduplicates and filters what the harness
already reports.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import Harness


# ---------------------------------------------------------------------------
# SurfaceTool
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SurfaceTool:
    """A single callable tool on a harness's surface.

    Each field maps to a real property of the tool as exposed by a harness
    adapter, so downstream consumers (task generators, packers) can make
    informed choices about which tools are available and safe to use.
    """

    #: Stable unique ID, e.g. ``"pi-extension:advisor-pi/advisor"`` or
    #: ``"claude-code:Bash"``.  Must be globally unique across all harnesses.
    surface_id: str

    #: The name exposed in the tool schema (what the model sees).
    tool_name: str

    #: Origin of the tool.
    source: str  # "extension" | "mcp" | "skill" | "plugin" | "builtin"

    #: Human-readable short label for the origin, e.g. ``"advisor-pi"`` or
    #: ``"github"``.
    source_ref: str

    #: Human-readable description of what the tool does.
    description: str

    #: JSON schema for the tool's input, if available; ``None`` otherwise.
    input_schema: dict | None = None

    #: ``True`` if the tool has no side effects (read-only / query).
    read_only: bool = False

    #: ``True`` if the tool calls external services (network I/O).
    is_remote: bool = False


# ---------------------------------------------------------------------------
# Harness.inventory()  (abstract, default empty)
# ---------------------------------------------------------------------------

# The method is added to the Harness base class at the bottom of this module
# after the registry is defined, so that the registry can reference
# ``Harness.inventory`` in its type hints without a circular import.


# ---------------------------------------------------------------------------
# SurfaceToolRegistry
# ---------------------------------------------------------------------------

class SurfaceToolRegistry:
    """Collect, deduplicate, and filter a harness's surface tools.

    Created once per harness instance and reused across task generation
    sessions.  The registry caches the last inventory call so that repeated
    lookups are cheap when the harness has not changed.
    """

    def __init__(self, harness: Harness) -> None:
        self._harness = harness
        self._cache: list[SurfaceTool] | None = None
        self._cache_live: bool | None = None

    def get(self, live: bool = True, source: str | None = None) -> list[SurfaceTool]:
        """Return the list of surface tools, optionally filtered by *source*.

        Parameters
        ----------
        live:
            Pass ``True`` to ask the harness for its live (daily) inventory,
            including extensions, skills, and MCP servers.  ``False`` returns
            the isolated / benchmark-safe surface.
        source:
            When given, only return tools whose ``source`` matches.  Pass
            ``None`` to return everything.

        Returns
        -------
        ``list[SurfaceTool]`` deduplicated by ``surface_id``, in the order the
        harness reported them.
        """
        # Cache hit — only valid when *live* matches the last call.
        if self._cache is not None and self._cache_live == live:
            tools = self._cache
        else:
            tools = self._harness.inventory(live=live)
            self._cache = tools
            self._cache_live = live

        if source is not None:
            tools = [t for t in tools if t.source == source]

        # Deduplicate by surface_id, preserving first-seen order.
        seen: set[str] = set()
        deduped: list[SurfaceTool] = []
        for t in tools:
            if t.surface_id not in seen:
                seen.add(t.surface_id)
                deduped.append(t)
        return deduped

    def refresh(self) -> list[SurfaceTool]:
        """Invalidate the cache and return the fresh inventory."""
        self._cache = None
        self._cache_live = None
        return self.get()


# ---------------------------------------------------------------------------
# SurfaceSelection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SurfaceSelection:
    """A deterministic snapshot of tools chosen for a task-generation run.

    The ``seed`` and ``generation_version`` fields make it possible to
    reproduce the exact same selection later, which is important for
    regression testing and fair par comparisons.
    """

    #: The chosen tools.
    tools: list[SurfaceTool]

    #: Opaque campaign identifier.
    campaign_id: str

    #: Random seed used during selection (for reproducibility).
    seed: int

    #: Version string for the selection algorithm / policy.
    generation_version: str


# ---------------------------------------------------------------------------
# TaskPack
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TaskPack:
    """A self-contained bundle of tools + tasks for a single campaign run.

    The ``pack_hash`` is a SHA-256 over a canonical JSON representation of the
    tools and tasks, so downstream consumers can verify that two packs are
    identical without deserialising the full object graph.
    """

    campaign_id: str
    seed: int
    generation_version: str
    tools: list[SurfaceTool]
    tasks: list[dict]
    pack_hash: str
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    @staticmethod
    def from_selection(
        selection: SurfaceSelection,
        tasks: list[dict],
        campaign_id: str,
        generation_version: str = "1.0.0",
    ) -> TaskPack:
        """Build a ``TaskPack`` from a ``SurfaceSelection`` and a list of task dicts.

        Parameters
        ----------
        selection:
            The tool selection to embed.
        tasks:
            Task dicts, each with keys ``id``, ``prompt``, ``files``,
            ``check``, ``oracle``, ``expected_tools``, ``difficulty``,
            ``mode``.
        campaign_id:
            Opaque campaign identifier.
        generation_version:
            Semantic version of the task-generation policy.

        Returns
        -------
        A new ``TaskPack`` with ``pack_hash`` computed.
        """
        canonical = {
            "campaign_id": campaign_id,
            "seed": selection.seed,
            "generation_version": generation_version,
            "tools": [
                {
                    "surface_id": t.surface_id,
                    "tool_name": t.tool_name,
                    "source": t.source,
                    "source_ref": t.source_ref,
                    "description": t.description,
                    "input_schema": t.input_schema,
                    "read_only": t.read_only,
                    "is_remote": t.is_remote,
                }
                for t in selection.tools
            ],
            "tasks": tasks,
        }
        pack_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, default=str).encode()
        ).hexdigest()

        return TaskPack(
            campaign_id=campaign_id,
            seed=selection.seed,
            generation_version=generation_version,
            tools=selection.tools,
            tasks=tasks,
            pack_hash=pack_hash,
        )


# ---------------------------------------------------------------------------
# Patch Harness.inventory() into the base class
# ---------------------------------------------------------------------------

def _inventory_default(self: Harness, live: bool = True) -> list[SurfaceTool]:
    """Default implementation: return an empty list.

    Concrete harnesses override this to return their actual tool inventory.
    """
    return []


# Attach the method to the Harness class (already imported at top-level via
# TYPE_CHECKING, but we need the runtime reference).
# Import here to avoid circular imports at module-load time.
from .base import Harness as _HarnessBase

_HarnessBase.inventory = _inventory_default
