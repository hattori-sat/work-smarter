from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from work_smarter.errors import AmbiguousEntityError, EntityNotFoundError
from work_smarter.knowledge import KnowledgeFeature
from work_smarter.knowledge.errors import KnowledgeConflictError, KnowledgeLinkError
from work_smarter.knowledge.models import (
    KnowledgeLink,
    KnowledgeLinkType,
    KnowledgeNote,
    KnowledgeNoteType,
    KnowledgePresentationMode,
    KnowledgeSearchField,
    MarpPresentation,
    MarpPresentationTemplate,
    SourceReference,
    SourceReferenceKind,
)
from work_smarter.knowledge.persistence import KNOWLEDGE_ENTITY_SPECS
from work_smarter.knowledge.presentations import MarpCompiler
from work_smarter.knowledge.service import KnowledgeService
from work_smarter.knowledge.templates import (
    initialize_knowledge_templates,
    presentation_template_path,
    template_path,
)
from work_smarter.storage.workspace import EntityRegistry, EntitySpec, Workspace


class ImportedRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["imported_record"] = "imported_record"
    title: str


@pytest.fixture
def knowledge_workspace(tmp_path: Path) -> Workspace:
    registry = EntityRegistry(KNOWLEDGE_ENTITY_SPECS)
    workspace = Workspace.initialize(tmp_path, registry)
    initialize_knowledge_templates(workspace)
    return workspace


@pytest.fixture
def knowledge(knowledge_workspace: Workspace) -> KnowledgeService:
    return KnowledgeService(knowledge_workspace)


def test_feature_registers_independent_persistence_and_templates(tmp_path: Path) -> None:
    from work_smarter.features import FeatureRegistry

    registry = FeatureRegistry()
    KnowledgeFeature().register(registry)

    spec = registry.entity_registry().require("knowledge_note")
    assert spec.model is KnowledgeNote
    assert spec.directory == "knowledge/notes"

    workspace = Workspace.initialize(tmp_path, registry.entity_registry())
    for initializer in registry.workspace_initializers:
        initializer(workspace)

    decision_template = template_path(workspace, KnowledgeNoteType.DECISION)
    assert "## Decision" in decision_template.read_text(encoding="utf-8")

    decision_template.write_text("# My decision template\n", encoding="utf-8")
    for initializer in registry.workspace_initializers:
        initializer(workspace)
    assert decision_template.read_text(encoding="utf-8") == "# My decision template\n"

    technical_report_template = template_path(workspace, KnowledgeNoteType.TECHNICAL_REPORT)
    assert "## Objective" in technical_report_template.read_text(encoding="utf-8")
    assert "## Method" in technical_report_template.read_text(encoding="utf-8")

    scientific_theme = presentation_template_path(
        workspace,
        MarpPresentationTemplate.SCIENTIFIC,
    )
    theme_content = scientific_theme.read_text(encoding="utf-8")
    assert "align-content: start" in theme_content
    assert "justify-content: flex-start" in theme_content
    assert "section img" in theme_content
    assert "h1" in theme_content
    assert "h2" in theme_content
    assert "h3" in theme_content

    scientific_theme.write_text("section { color: rebeccapurple; }\n", encoding="utf-8")
    for initializer in registry.workspace_initializers:
        initializer(workspace)
    assert scientific_theme.read_text(encoding="utf-8") == ("section { color: rebeccapurple; }\n")


def test_knowledge_package_does_not_import_gtd() -> None:
    source_root = Path(__file__).parents[1] / "src"
    environment = {**os.environ, "PYTHONPATH": str(source_root)}

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import work_smarter.knowledge; "
                "import sys; "
                "assert 'work_smarter.gtd' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr


def test_schema_covers_all_note_types_and_rejects_unknown_metadata() -> None:
    assert {kind.value for kind in KnowledgeNoteType} == {
        "note",
        "decision",
        "how_to",
        "reference",
        "meeting_note",
        "technical_report",
    }

    with pytest.raises(ValidationError):
        KnowledgeNote.model_validate(
            {
                "id": "KN-1",
                "title": "Strict metadata",
                "unexpected": True,
            }
        )


def test_technical_report_template_renders_as_read_only_marp_projection(
    knowledge: KnowledgeService,
    knowledge_workspace: Workspace,
) -> None:
    created = knowledge.create(
        title="Database adapter rollout",
        note_type=KnowledgeNoteType.TECHNICAL_REPORT,
        body=(
            "## Executive Summary\n\nAdapters remove database lock-in.\n\n"
            "## Evidence\n\n- SQLite acceptance is green.\n\n"
            "```python\n## This is code, not a slide\n```\n"
        ),
    )
    source_path = knowledge_workspace.root / created.path
    source_before = source_path.read_bytes()
    events_before = knowledge_workspace.event_store.read_all()

    presentation = knowledge.render_presentation(
        created.note.id[:12],
        mode=KnowledgePresentationMode.TECHNICAL_REPORT,
        theme="gaia",
        paginate=False,
    )

    assert presentation.source_id == created.note.id
    assert presentation.source_revision == 1
    assert presentation.mode is KnowledgePresentationMode.TECHNICAL_REPORT
    assert presentation.template is MarpPresentationTemplate.SCIENTIFIC
    assert presentation.theme == "gaia"
    assert presentation.paginate is False
    assert presentation.media_type == "text/markdown"
    assert presentation.file_extension == ".marp.md"
    assert presentation.markdown.startswith(
        "---\nmarp: true\ntheme: gaia\npaginate: false\nstyle: |\n"
    )
    assert "  section {" in presentation.markdown
    assert "    justify-content: flex-start;" in presentation.markdown
    assert "  section img," in presentation.markdown
    assert "# Database adapter rollout" in presentation.markdown
    assert "<!-- Source: " + created.note.id + "@1 -->" in presentation.markdown
    assert "\n---\n\n## Executive Summary" in presentation.markdown
    assert "\n---\n\n## Evidence" in presentation.markdown
    assert "\n---\n\n## This is code" not in presentation.markdown
    assert "```python\n## This is code, not a slide\n```" in presentation.markdown
    assert source_path.read_bytes() == source_before
    assert knowledge_workspace.event_store.read_all() == events_before


def test_marp_projection_uses_user_overridden_scientific_theme(
    knowledge: KnowledgeService,
    knowledge_workspace: Workspace,
) -> None:
    presentation_template_path(
        knowledge_workspace,
        MarpPresentationTemplate.SCIENTIFIC,
    ).write_text(
        "section { background: #123456; }\n",
        encoding="utf-8",
    )
    created = knowledge.create(title="Custom scientific style")

    rendered = knowledge.render_presentation(created.note.id)

    assert rendered.template is MarpPresentationTemplate.SCIENTIFIC
    assert "  section { background: #123456; }" in rendered.markdown


def test_marp_projection_rejects_unsafe_theme_without_side_effects(
    knowledge: KnowledgeService,
    knowledge_workspace: Workspace,
) -> None:
    created = knowledge.create(title="Safe projection")
    events_before = knowledge_workspace.event_store.read_all()

    with pytest.raises(ValidationError, match="theme"):
        knowledge.render_presentation(created.note.id, theme="default\npaginate: false")

    assert knowledge_workspace.event_store.read_all() == events_before


def test_html_preview_compiles_projection_without_mutating_knowledge(
    knowledge: KnowledgeService,
    knowledge_workspace: Workspace,
) -> None:
    class FakeCompiler(MarpCompiler):
        def compile_html(self, presentation: MarpPresentation) -> str:
            return f"<!doctype html><title>{presentation.source_id}</title>"

    created = knowledge.create(
        title="HTML preview",
        note_type=KnowledgeNoteType.TECHNICAL_REPORT,
        body="## Outcome\n\nPreviewed.\n",
    )
    source_path = knowledge_workspace.root / created.path
    source_before = source_path.read_bytes()
    events_before = knowledge_workspace.event_store.read_all()

    rendered = knowledge.render_html_presentation(
        created.note.id[:12],
        compiler=FakeCompiler(),
    )

    assert rendered.source_id == created.note.id
    assert rendered.source_revision == 1
    assert rendered.media_type == "text/html"
    assert rendered.file_extension == ".html"
    assert rendered.html.startswith("<!doctype html>")
    assert source_path.read_bytes() == source_before
    assert knowledge_workspace.event_store.read_all() == events_before


def test_create_normalizes_metadata_preserves_markdown_and_reloads(
    knowledge: KnowledgeService,
    knowledge_workspace: Workspace,
) -> None:
    created = knowledge.create(
        title="  Architecture decision  ",
        note_type=KnowledgeNoteType.DECISION,
        body="# Context\n\nKeep this **Markdown**.\n",
        tags=[" Architecture ", "python", "PYTHON"],
        aliases=["ADR One", " adr-one "],
        sources=[
            SourceReference(
                kind=SourceReferenceKind.URL,
                locator="https://example.com/design",
                title="Design source",
            )
        ],
    )

    assert created.note.title == "Architecture decision"
    assert created.note.note_type is KnowledgeNoteType.DECISION
    assert created.note.tags == ["architecture", "python"]
    assert created.note.aliases == ["ADR One", "adr-one"]
    assert created.body == "# Context\n\nKeep this **Markdown**.\n"
    assert created.path == f"knowledge/notes/{created.note.id}.md"
    assert created.note.created_at.tzinfo is not None
    assert created.note.updated_at == created.note.created_at

    reloaded = KnowledgeService(knowledge_workspace).get(created.note.id[:12])
    assert reloaded == created
    assert KnowledgeService(knowledge_workspace).get("adr-one").note.id == created.note.id

    events = knowledge_workspace.event_store.read_all()
    assert events[-1].type == "knowledge.note.created"
    assert events[-1].entity_id == created.note.id


def test_get_alias_requires_an_unambiguous_exact_match(
    knowledge: KnowledgeService,
    knowledge_workspace: Workspace,
) -> None:
    first = knowledge.create(title="First", aliases=["shared"])
    second = KnowledgeNote(id="KN-MANUAL", title="Second", aliases=["shared"])
    knowledge_workspace.write(second, "Second body")

    with pytest.raises(AmbiguousEntityError):
        knowledge.get("shared")
    with pytest.raises(EntityNotFoundError):
        knowledge.get("missing")
    assert knowledge.get(first.note.id).note.id == first.note.id


def test_create_from_template_update_list_and_search_public_fields(
    knowledge: KnowledgeService,
    knowledge_workspace: Workspace,
) -> None:
    first = knowledge.create(
        title="Deploy the service",
        note_type=KnowledgeNoteType.HOW_TO,
        tags=["operations"],
    )
    second = knowledge.create(
        title="Python packaging",
        body="A wheel contains the reusable artifact.\n",
        tags=["build-system"],
    )

    assert "## Procedure" in first.body
    updated = knowledge.update(
        second.note.id,
        title="Package the Python service",
        body="The release NEEDLE lives in a wheel.\n",
        tags=["Release", "Python"],
        aliases=[],
        sources=[],
    )
    assert updated.note.revision == 2
    assert updated.note.tags == ["python", "release"]
    assert updated.body == "The release NEEDLE lives in a wheel.\n"
    assert updated.note.updated_at >= updated.note.created_at

    listed = knowledge.list(note_types=[KnowledgeNoteType.HOW_TO])
    assert [item.note.id for item in listed] == [first.note.id]
    assert [item.note.id for item in knowledge.list(tags=["PYTHON"])] == [updated.note.id]

    title_hits = knowledge.search("package", fields=[KnowledgeSearchField.TITLE])
    tag_hits = knowledge.search("release", fields=[KnowledgeSearchField.TAG])
    body_hits = knowledge.search("needle", fields=[KnowledgeSearchField.BODY])
    assert [(hit.note.id, hit.matched_fields) for hit in title_hits] == [
        (updated.note.id, [KnowledgeSearchField.TITLE])
    ]
    assert [hit.note.id for hit in tag_hits] == [updated.note.id]
    assert [hit.note.id for hit in body_hits] == [updated.note.id]

    reloaded = KnowledgeService(knowledge_workspace).get(updated.note.id)
    assert reloaded.note.revision == 2
    assert reloaded.body == updated.body
    assert knowledge_workspace.event_store.read_all()[-1].type == "knowledge.note.updated"


def test_links_are_explicit_validated_and_exposed_as_backlinks(
    knowledge: KnowledgeService,
) -> None:
    target = knowledge.create(title="Authoritative design")
    source = knowledge.create(
        title="Implementation notes",
        links=[
            KnowledgeLink(
                target_id=target.note.id,
                relation=KnowledgeLinkType.DERIVED_FROM,
                label="Design basis",
            )
        ],
    )

    backlinks = knowledge.backlinks(target.note.id[:12])
    assert len(backlinks) == 1
    assert backlinks[0].source.note.id == source.note.id
    assert backlinks[0].link.target_id == target.note.id

    duplicate = KnowledgeLink(
        target_id=target.note.id,
        relation=KnowledgeLinkType.DERIVED_FROM,
    )
    with pytest.raises(KnowledgeLinkError, match="duplicate"):
        knowledge.update(source.note.id, links=[duplicate, duplicate])
    with pytest.raises(KnowledgeLinkError, match="does not exist"):
        knowledge.create(
            title="Broken through the service",
            links=[KnowledgeLink(target_id="KN-MISSING")],
        )
    with pytest.raises(KnowledgeLinkError, match="itself"):
        knowledge.update(
            target.note.id,
            links=[KnowledgeLink(target_id=target.note.id)],
        )


def test_create_refuses_global_id_and_alias_collisions(knowledge: KnowledgeService) -> None:
    first = knowledge.create(title="First", note_id="KN-STABLE", aliases=["one"])

    with pytest.raises(KnowledgeConflictError, match="ID"):
        knowledge.create(title="Duplicate ID", note_id=first.note.id)
    with pytest.raises(KnowledgeConflictError, match="alias"):
        knowledge.create(title="Duplicate alias", aliases=["ONE"])


def test_promote_record_uses_only_the_generic_record_contract(tmp_path: Path) -> None:
    registry = EntityRegistry(
        (
            *KNOWLEDGE_ENTITY_SPECS,
            EntitySpec("imported_record", ImportedRecord, "imports"),
        )
    )
    workspace = Workspace.initialize(tmp_path, registry)
    initialize_knowledge_templates(workspace)
    imported = ImportedRecord(id="EXT-42", title="External design")
    source = workspace.write(imported, "# External design\n\nOriginal Markdown.\n")

    promoted = KnowledgeService(workspace).promote_record(
        source,
        note_type=KnowledgeNoteType.REFERENCE,
        tags=["Imported"],
    )

    assert promoted.note.title == imported.title
    assert promoted.body == source.body
    assert promoted.note.sources == [
        SourceReference(
            kind=SourceReferenceKind.ENTITY,
            locator=imported.id,
            title="imported_record: External design",
        )
    ]
    event = workspace.event_store.read_all()[-1]
    assert event.type == "knowledge.note.promoted"
    assert event.payload["source_id"] == imported.id

    event_count = len(workspace.event_store.read_all())
    repeated = KnowledgeService(workspace).promote_record(
        source,
        note_type=KnowledgeNoteType.HOW_TO,
        title="A repeat must not overwrite the first promotion",
    )
    assert repeated == promoted
    assert len(workspace.event_store.read_all()) == event_count


def test_promote_record_refuses_multiple_direct_edit_claims(tmp_path: Path) -> None:
    registry = EntityRegistry(
        (
            *KNOWLEDGE_ENTITY_SPECS,
            EntitySpec("imported_record", ImportedRecord, "imports"),
        )
    )
    workspace = Workspace.initialize(tmp_path, registry)
    imported = ImportedRecord(id="EXT-42", title="External design")
    source = workspace.write(imported, "Original Markdown.\n")
    source_reference = SourceReference(
        kind=SourceReferenceKind.ENTITY,
        locator=imported.id,
        title="imported_record: External design",
    )
    workspace.write(
        KnowledgeNote(id="KN-FIRST", title="First claim", sources=[source_reference]),
        "First.\n",
    )
    workspace.write(
        KnowledgeNote(id="KN-SECOND", title="Second claim", sources=[source_reference]),
        "Second.\n",
    )

    with pytest.raises(KnowledgeConflictError, match="multiple knowledge notes"):
        KnowledgeService(workspace).promote_record(source)


def test_doctor_reports_orphan_broken_and_duplicate_links(
    knowledge: KnowledgeService,
    knowledge_workspace: Workspace,
) -> None:
    target = knowledge.create(title="Target")
    orphan = knowledge.create(title="Unconnected")
    sourced = knowledge.create(
        title="Connected to a source",
        sources=[
            SourceReference(
                kind=SourceReferenceKind.URL,
                locator="https://example.com/source",
            )
        ],
    )
    duplicate = KnowledgeLink(
        target_id=target.note.id,
        relation=KnowledgeLinkType.RELATED_TO,
    )
    manually_edited = KnowledgeNote(
        id="KN-MANUAL",
        title="Manual links",
        links=[
            duplicate,
            duplicate,
            KnowledgeLink(target_id="KN-NOT-THERE"),
        ],
    )
    knowledge_workspace.write(manually_edited, "Edited outside the service.\n")

    report = knowledge.doctor()

    assert report.valid is False
    assert report.counts == {
        "notes": 4,
        "orphan": 1,
        "broken_link": 1,
        "duplicate_link": 1,
    }
    issues = {(issue.code, issue.note_id, issue.target_id) for issue in report.issues}
    assert ("orphan", orphan.note.id, None) in issues
    assert ("broken_link", manually_edited.id, "KN-NOT-THERE") in issues
    assert ("duplicate_link", manually_edited.id, target.note.id) in issues
    assert not any(
        issue.note_id == target.note.id and issue.code == "orphan" for issue in report.issues
    )
    assert not any(
        issue.note_id == sourced.note.id and issue.code == "orphan" for issue in report.issues
    )
