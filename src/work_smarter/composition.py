"""Application composition root for built-in and future feature packages."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from work_smarter.errors import InvalidDocumentError
from work_smarter.features import Feature, FeatureRegistry, discover_features
from work_smarter.gtd import GtdFeature
from work_smarter.knowledge import KnowledgeFeature
from work_smarter.project_management import ProjectManagementFeature
from work_smarter.shared.persistence.database import (
    DatabaseBackend,
    DatabaseBackendRegistry,
    DatabaseConfiguration,
    create_database_backend,
)
from work_smarter.storage.workspace import DEFAULT_WORKSPACE_FEATURES, Workspace

BUILTIN_FEATURES: tuple[type[Feature], ...] = (
    GtdFeature,
    KnowledgeFeature,
    ProjectManagementFeature,
)


def available_features(extra: Iterable[Feature] = ()) -> dict[str, Feature]:
    """Return feature descriptors, preferring explicitly installed packages."""

    available = {feature_type().name: feature_type() for feature_type in BUILTIN_FEATURES}
    for feature in (*discover_features(), *extra):
        available[feature.name] = feature
    return available


def compose_features(
    enabled: Iterable[str],
    *,
    extra: Iterable[Feature] = (),
) -> FeatureRegistry:
    available = available_features(extra)
    registry = FeatureRegistry()
    for name in enabled:
        feature = available.get(name)
        if feature is None:
            raise InvalidDocumentError(
                f"Workspace enables unavailable feature {name!r}; install or disable it"
            )
        feature.register(registry)
    return registry


def configured_database(
    root: Path | str,
    *,
    database_registry: DatabaseBackendRegistry | None = None,
) -> DatabaseBackend:
    """Resolve the configured database through the provider-neutral registry."""

    probe = Workspace(root)
    configuration = (
        probe.settings().database if probe.config_path.is_file() else DatabaseConfiguration()
    )
    return create_database_backend(
        probe.root,
        configuration,
        registry=database_registry,
    )


def initialize_workspace(
    root: Path | str,
    *,
    database_registry: DatabaseBackendRegistry | None = None,
) -> Workspace:
    """Initialize directories for the features enabled by workspace config."""

    probe = Workspace(root)
    enabled = (
        probe.settings().features if probe.config_path.is_file() else DEFAULT_WORKSPACE_FEATURES
    )
    composition = compose_features(enabled)
    workspace = Workspace.initialize(root, composition.entity_registry())
    configured_database(
        workspace.root,
        database_registry=database_registry,
    ).migrate()
    for initializer in composition.workspace_initializers:
        initializer(workspace)
    return workspace


def open_workspace(root: Path | str) -> Workspace:
    """Open a workspace after composing exactly its enabled feature codecs."""

    probe = Workspace.open(root)
    registry = compose_features(probe.settings().features).entity_registry()
    return Workspace.open(root, registry)
