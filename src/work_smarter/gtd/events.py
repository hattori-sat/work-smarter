"""Namespaced audit event names owned by the GTD feature."""

from enum import StrEnum


class EventType(StrEnum):
    CAPTURED = "gtd.inbox.captured"
    CLARIFIED = "gtd.inbox.clarified"
    TASK_STARTED = "gtd.task.started"
    TASK_STOPPED = "gtd.task.stopped"
    TASK_COMPLETED = "gtd.task.completed"
    TASK_DEFINED = "gtd.task.defined"
    TASK_CONDITION_CHECKED = "gtd.task.condition.checked"
    TASK_LINKED = "gtd.task.linked"
    TASK_READY = "gtd.task.ready"
    TASK_SWITCHED = "gtd.task.switched"
    PROJECT_COMPLETED = "gtd.project.completed"
    REVIEW_COMPLETED = "gtd.review.completed"
