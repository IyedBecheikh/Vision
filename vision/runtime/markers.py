"""Strict marker parsing and rendering."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ValidationError


@dataclass(frozen=True)
class Marker:
    start: str
    end: str


USER_MANAGED = Marker(
    "<!-- vision-user-managed-start -->",
    "<!-- vision-user-managed-end -->",
)
WORKFLOW_MANAGED = Marker(
    "<!-- vision-managed-start -->",
    "<!-- vision-managed-end -->",
)
PROJECT_PERSONALIZATION = Marker(
    "<!-- vision-project-personalization-start -->",
    "<!-- vision-project-personalization-end -->",
)
PROJECT_LOCAL = Marker(
    "<!-- vision-project-local-instructions-start -->",
    "<!-- vision-project-local-instructions-end -->",
)
VISION_HOME_TOKEN = "{{VISION_HOME}}"


def substitute_vision_home(text: str, *, home_display: str) -> str:
    """Replace the platform-resolved workflow-home placeholder in shared content."""

    return text.replace(VISION_HOME_TOKEN, home_display)


def _bounds(text: str, marker: Marker) -> tuple[int, int]:
    if text.count(marker.start) != 1 or text.count(marker.end) != 1:
        raise ValidationError(
            f"expected exactly one marker pair: {marker.start} / {marker.end}"
        )
    start = text.index(marker.start) + len(marker.start)
    end = text.index(marker.end)
    if start > end:
        raise ValidationError(f"marker end precedes start: {marker.start}")
    return start, end


def extract(text: str, marker: Marker) -> str:
    start, end = _bounds(text, marker)
    body = text[start:end]
    if body.startswith("\n"):
        body = body[1:]
    if body.endswith("\n"):
        body = body[:-1]
    return body


def replace(text: str, marker: Marker, body: str) -> str:
    start, end = _bounds(text, marker)
    normalized = body.strip("\n")
    replacement = "\n" + normalized + "\n" if normalized else "\n"
    return text[:start] + replacement + text[end:]


def remove_region(text: str, marker: Marker) -> str:
    start, end = _bounds(text, marker)
    start -= len(marker.start)
    end += len(marker.end)
    remaining = text[:start] + text[end:]
    if not remaining.strip():
        return ""
    return remaining.rstrip("\n") + "\n"


def append_region(text: str, marker: Marker, body: str) -> str:
    if marker.start in text or marker.end in text:
        raise ValidationError(f"partial or unexpected marker already present: {marker.start}")
    prefix = text.rstrip() + "\n\n" if text.strip() else ""
    normalized = body.strip("\n")
    middle = f"\n{normalized}\n" if normalized else "\n"
    return prefix + marker.start + middle + marker.end + "\n"
