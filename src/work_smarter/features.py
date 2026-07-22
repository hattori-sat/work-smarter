"""Feature contracts used to keep GTD and future tools independently evolvable."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Protocol, runtime_checkable

from work_smarter.storage.workspace import EntityRegistry, EntitySpec


@runtime_checkable
class Feature(Protocol):
    """A separately deployable capability hosted by Work Smarter.

    Features may expose CLI commands, API routers, validators, and event
    subscribers.  The core deliberately treats those objects as opaque so a
    future User Story Mapping or TBP feature does not depend on GTD internals.
    """

    name: str
    version: str

    def register(self, registry: FeatureRegistry) -> None:
        """Register this feature's optional integration points."""


@dataclass(slots=True)
class FeatureRegistry:
    """Runtime registry for independently implemented product features."""

    cli_apps: dict[str, Any] = field(default_factory=dict)
    api_routers: list[Any] = field(default_factory=list)
    validators: list[Any] = field(default_factory=list)
    event_handlers: dict[str, list[Any]] = field(default_factory=dict)
    entity_specs: list[EntitySpec] = field(default_factory=list)
    workspace_initializers: list[Any] = field(default_factory=list)

    def add_cli(self, name: str, app: Any) -> None:
        if name in self.cli_apps:
            raise ValueError(f"CLI feature already registered: {name}")
        self.cli_apps[name] = app

    def add_router(self, router: Any) -> None:
        self.api_routers.append(router)

    def add_validator(self, validator: Any) -> None:
        self.validators.append(validator)

    def subscribe(self, event_type: str, handler: Any) -> None:
        self.event_handlers.setdefault(event_type, []).append(handler)

    def add_entity(self, spec: EntitySpec) -> None:
        if any(existing.kind == spec.kind for existing in self.entity_specs):
            raise ValueError(f"Entity kind already registered: {spec.kind}")
        self.entity_specs.append(spec)

    def entity_registry(self) -> EntityRegistry:
        return EntityRegistry(tuple(self.entity_specs))

    def add_workspace_initializer(self, initializer: Any) -> None:
        self.workspace_initializers.append(initializer)


def discover_features() -> list[Feature]:
    """Load installed feature packages through the stable entry-point group."""

    discovered: list[Feature] = []
    for entry_point in entry_points(group="work_smarter.features"):
        feature_factory = entry_point.load()
        feature = feature_factory()
        if not isinstance(feature, Feature):
            raise TypeError(f"{entry_point.name} does not implement Feature")
        discovered.append(feature)
    return discovered
