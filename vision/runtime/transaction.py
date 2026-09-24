"""Small compensating filesystem transaction with atomic per-file writes."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import TransactionError, ValidationError


@dataclass(frozen=True)
class Mutation:
    path: Path
    content: bytes | None
    mode: int = 0o644

    @property
    def action(self) -> str:
        if self.content is None:
            return "delete"
        return "replace" if self.path.exists() else "create"


@dataclass
class _Snapshot:
    path: Path
    existed: bool
    content: bytes | None
    mode: int | None


def summarize(mutations: list[Mutation], *, path_limit: int = 12) -> dict[str, object]:
    grouped: dict[str, list[str]] = {"create": [], "replace": [], "delete": []}
    for mutation in mutations:
        grouped[mutation.action].append(str(mutation.path))
    return {
        "counts": {action: len(paths) for action, paths in grouped.items()},
        "paths": {action: paths[:path_limit] for action, paths in grouped.items()},
        "truncated": any(len(paths) > path_limit for paths in grouped.values()),
    }


def apply(mutations: list[Mutation]) -> None:
    paths = [mutation.path.resolve(strict=False) for mutation in mutations]
    if len(paths) != len(set(paths)):
        raise ValidationError("transaction contains duplicate target paths")
    snapshots: list[_Snapshot] = []
    created_directories: list[Path] = []
    try:
        for mutation in mutations:
            path = mutation.path
            if path.is_symlink():
                raise ValidationError(f"refusing to replace symlink target: {path}")
            existed = path.exists()
            if existed and not path.is_file():
                raise ValidationError(f"transaction target is not a regular file: {path}")
            snapshots.append(
                _Snapshot(
                    path,
                    existed,
                    path.read_bytes() if existed else None,
                    path.stat().st_mode & 0o777 if existed else None,
                )
            )
            _ensure_parent(path.parent, created_directories)
            if mutation.content is None:
                if existed:
                    path.unlink()
            else:
                _atomic_write(path, mutation.content, mutation.mode)
    except Exception as error:
        rollback_errors = _rollback(snapshots, created_directories)
        suffix = f"; rollback errors: {rollback_errors}" if rollback_errors else ""
        raise TransactionError(f"transaction failed: {error}{suffix}") from error


def _ensure_parent(parent: Path, created: list[Path]) -> None:
    missing: list[Path] = []
    cursor = parent
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if cursor.is_symlink():
        raise ValidationError(f"refusing to write through symlink parent: {cursor}")
    for directory in reversed(missing):
        directory.mkdir()
        created.append(directory)


def _atomic_write(path: Path, content: bytes, mode: int) -> None:
    handle, temporary_name = tempfile.mkstemp(prefix=".vision-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        if path.read_bytes() != content:
            raise OSError(f"post-write verification failed: {path}")
    finally:
        if temporary.exists():
            temporary.unlink()


def _rollback(snapshots: list[_Snapshot], created: list[Path]) -> list[str]:
    errors: list[str] = []
    for snapshot in reversed(snapshots):
        try:
            if snapshot.existed:
                _atomic_write(
                    snapshot.path,
                    snapshot.content or b"",
                    snapshot.mode or 0o644,
                )
            elif snapshot.path.exists():
                snapshot.path.unlink()
        except Exception as error:  # pragma: no cover - exercised by fault injection
            errors.append(f"{snapshot.path}: {error}")
    for directory in reversed(created):
        try:
            directory.rmdir()
        except OSError:
            pass
    return errors
