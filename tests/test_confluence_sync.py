from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from work_smarter.confluence.client import ConfluencePage, ConfluenceSpace
from work_smarter.confluence.errors import ConfluenceSyncConflictError
from work_smarter.confluence.models import ConfluenceTarget, SyncAction, SyncDirection
from work_smarter.confluence.service import ConfluencePublishingService
from work_smarter.publishing.models import PublicationTarget
from work_smarter.storage.frontmatter import read_markdown
from work_smarter.storage.workspace import EntityRegistry, EntitySpec, Workspace


class PublishableNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    id: str
    kind: Literal["publishable_note"] = "publishable_note"
    title: str
    publications: list[PublicationTarget] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    revision: int = 1


class FakeClient:
    def __init__(self):
        self.space = ConfluenceSpace(id="42", key="ENG", name="Engineering")
        self.pages: dict[str, ConfluencePage] = {}
        self.calls: list[tuple[str, object]] = []
        self.next_page_id = 100

    def resolve_space(self, key: str) -> ConfluenceSpace:
        self.calls.append(("resolve_space", key))
        assert key == self.space.key
        return self.space

    def get_page(self, page_id: str) -> ConfluencePage:
        self.calls.append(("get_page", page_id))
        return self.pages[page_id].model_copy(deep=True)

    def create_page(
        self,
        *,
        space_id: str,
        title: str,
        storage: str,
        parent_id: str | None = None,
    ) -> ConfluencePage:
        self.calls.append(("create_page", {"space_id": space_id, "title": title}))
        page_id = str(self.next_page_id)
        self.next_page_id += 1
        page = ConfluencePage(
            id=page_id,
            title=title,
            space_id=space_id,
            parent_id=parent_id,
            version=1,
            storage=storage,
        )
        self.pages[page_id] = page
        return page.model_copy(deep=True)

    def update_page(
        self,
        *,
        page_id: str,
        title: str,
        storage: str,
        current_version: int,
        parent_id: str | None = None,
        message: str = "Published by Work Smarter",
    ) -> ConfluencePage:
        self.calls.append(("update_page", {"page_id": page_id, "version": current_version}))
        current = self.pages[page_id]
        assert current.version == current_version
        page = ConfluencePage(
            id=page_id,
            title=title,
            space_id=current.space_id,
            parent_id=parent_id,
            version=current_version + 1,
            storage=storage,
        )
        self.pages[page_id] = page
        return page.model_copy(deep=True)

    def edit_remote(self, page_id: str, *, storage: str, title: str | None = None) -> None:
        page = self.pages[page_id]
        self.pages[page_id] = page.model_copy(
            update={
                "storage": storage,
                "title": title or page.title,
                "version": page.version + 1,
            }
        )


@pytest.fixture
def sync_workspace(tmp_path: Path) -> Workspace:
    workspace = Workspace.initialize(
        tmp_path,
        EntityRegistry((EntitySpec("publishable_note", PublishableNote, "notes"),)),
    )
    workspace.write(
        PublishableNote(id="DOC-1", title="Runbook"),
        "# Runbook\n\nInitial body.\n",
    )
    return workspace


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def publishing(
    sync_workspace: Workspace,
    fake_client: FakeClient,
) -> ConfluencePublishingService:
    return ConfluencePublishingService(sync_workspace, fake_client)


def test_configure_writes_frontmatter_mapping_without_machine_state(
    publishing: ConfluencePublishingService,
    sync_workspace: Workspace,
) -> None:
    document = publishing.configure(
        "DOC-1",
        space_key="ENG",
        parent_id="50",
        title="Published runbook",
    )

    assert document.publication.target == {
        "space_key": "ENG",
        "parent_id": "50",
        "title": "Published runbook",
    }
    metadata = read_markdown(sync_workspace.root / "notes/DOC-1.md").metadata
    assert metadata["publications"] == [
        {
            "provider": "confluence",
            "target": {
                "space_key": "ENG",
                "parent_id": "50",
                "title": "Published runbook",
            },
        }
    ]
    assert not (sync_workspace.state_dir / "sync/confluence/DOC-1.json").exists()
    assert sync_workspace.event_store.read_all()[-1].type == "confluence.mapping.configured"


def test_dry_run_create_is_read_only_then_push_is_idempotent(
    publishing: ConfluencePublishingService,
    sync_workspace: Workspace,
    fake_client: FakeClient,
) -> None:
    publishing.configure("DOC-1", space_key="ENG")
    before = (sync_workspace.root / "notes/DOC-1.md").read_bytes()
    event_count = len(sync_workspace.event_store.read_all())

    preview = publishing.push("DOC-1", dry_run=True)

    assert preview.plan.action is SyncAction.CREATE_REMOTE
    assert not preview.mutated
    assert fake_client.calls == []
    assert (sync_workspace.root / "notes/DOC-1.md").read_bytes() == before
    assert len(sync_workspace.event_store.read_all()) == event_count

    pushed = publishing.push("DOC-1")
    assert pushed.plan.action is SyncAction.CREATE_REMOTE
    assert pushed.mutated
    assert pushed.page_id == "100"
    assert (sync_workspace.state_dir / "sync/confluence/DOC-1.json").is_file()
    mapped = publishing.get_document("DOC-1")
    assert ConfluenceTarget.model_validate(mapped.publication.target).page_id == "100"

    repeated = publishing.push("DOC-1")
    assert repeated.plan.action is SyncAction.NOOP
    assert not repeated.mutated
    assert [name for name, _ in fake_client.calls].count("create_page") == 1


def test_push_detects_remote_ahead_and_two_sided_conflict(
    publishing: ConfluencePublishingService,
    sync_workspace: Workspace,
    fake_client: FakeClient,
) -> None:
    publishing.configure("DOC-1", space_key="ENG")
    created = publishing.push("DOC-1")
    page_id = created.page_id
    assert page_id

    fake_client.edit_remote(page_id, storage="<p>Remote edit</p>")
    with pytest.raises(ConfluenceSyncConflictError, match="remote_ahead"):
        publishing.push("DOC-1")

    record = sync_workspace.find_record("DOC-1")
    sync_workspace.write(record.entity, "# Runbook\n\nLocal edit.\n")
    plan = publishing.plan("DOC-1", direction=SyncDirection.PUSH)
    assert plan.action is SyncAction.CONFLICT
    with pytest.raises(ConfluenceSyncConflictError, match="conflict"):
        publishing.push("DOC-1")

    forced = publishing.push("DOC-1", force=True)
    assert forced.mutated
    assert fake_client.pages[page_id].storage.find("Local edit") >= 0


def test_pull_updates_remote_only_change_and_refuses_local_loss(
    publishing: ConfluencePublishingService,
    sync_workspace: Workspace,
    fake_client: FakeClient,
) -> None:
    publishing.configure("DOC-1", space_key="ENG")
    page_id = publishing.push("DOC-1").page_id
    assert page_id
    fake_client.edit_remote(page_id, storage="<h1>Runbook</h1><p>Remote body.</p>")

    pulled = publishing.pull("DOC-1")

    assert pulled.plan.action is SyncAction.UPDATE_LOCAL
    assert pulled.mutated
    assert sync_workspace.find_record("DOC-1").body == "# Runbook\n\nRemote body.\n"

    local = sync_workspace.find_record("DOC-1")
    sync_workspace.write(local.entity, "# Runbook\n\nUnsynced local.\n")
    with pytest.raises(ConfluenceSyncConflictError, match="local_ahead"):
        publishing.pull("DOC-1")


def test_untracked_mapping_and_lossy_pull_require_force(
    publishing: ConfluencePublishingService,
    fake_client: FakeClient,
) -> None:
    fake_client.pages["777"] = ConfluencePage(
        id="777",
        title="Remote",
        space_id="42",
        version=3,
        storage=(
            '<p>Before</p><ac:structured-macro ac:name="jira"></ac:structured-macro><p>After</p>'
        ),
    )
    publishing.configure("DOC-1", space_key="ENG", page_id="777")

    assert (
        publishing.plan("DOC-1", direction=SyncDirection.PULL).action is SyncAction.UNTRACKED_REMOTE
    )
    with pytest.raises(ConfluenceSyncConflictError, match="untracked_remote"):
        publishing.pull("DOC-1")
    with pytest.raises(ConfluenceSyncConflictError, match="conversion warnings"):
        publishing.pull("DOC-1", force=True)

    adopted = publishing.pull("DOC-1", force=True, accept_loss=True)
    assert adopted.mutated
    assert adopted.warnings
    assert "Unsupported Confluence macro" in publishing.workspace.find_record("DOC-1").body


def test_configure_rejects_unknown_publishable_shape_without_writing(
    sync_workspace: Workspace,
    fake_client: FakeClient,
) -> None:
    class NoPublication(BaseModel):
        id: str
        kind: Literal["no_publication"] = "no_publication"
        title: str

    registry = EntityRegistry(
        (
            EntitySpec("publishable_note", PublishableNote, "notes"),
            EntitySpec("no_publication", NoPublication, "other"),
        )
    )
    workspace = Workspace.initialize(sync_workspace.root, registry)
    workspace.write(NoPublication(id="OTHER-1", title="No mapping"), "Body\n")
    service = ConfluencePublishingService(workspace, fake_client)

    with pytest.raises(ValueError, match="publication metadata"):
        service.configure("OTHER-1", space_key="ENG")

    assert workspace.find_record("OTHER-1").body == "Body\n"
