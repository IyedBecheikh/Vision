"""SemVer and GitHub Release acquisition for lifecycle commands."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from functools import total_ordering
from pathlib import Path, PurePosixPath

from .errors import ValidationError


RELEASES_URL = (
    "https://api.github.com/repos/IyedBecheikh/vision/releases?per_page=100"
)


@total_ordering
@dataclass(frozen=True)
class SemVer:
    core: tuple[int, int, int]
    prerelease: tuple[str, ...] = ()

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        if self.core != other.core:
            return self.core < other.core
        if not self.prerelease:
            return False
        if not other.prerelease:
            return True
        for left, right in zip(self.prerelease, other.prerelease):
            if left == right:
                continue
            if left.isdigit() and right.isdigit():
                return int(left) < int(right)
            if left.isdigit() != right.isdigit():
                return left.isdigit()
            return left < right
        return len(self.prerelease) < len(other.prerelease)


_SEMVER = re.compile(
    r"^(?:v)?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def parse_semver(value: str) -> SemVer:
    match = _SEMVER.fullmatch(value.strip())
    if match is None:
        raise ValidationError(f"invalid semantic version: {value!r}")
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
    for identifier in prerelease:
        if identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0"):
            raise ValidationError(f"invalid semantic version: {value!r}")
    return SemVer(tuple(int(match.group(index)) for index in range(1, 4)), prerelease)


@dataclass(frozen=True)
class ReleaseSelection:
    version_text: str
    version: SemVer
    zip_name: str
    zip_url: str
    checksums_url: str
    release_notes: str = ""
    release_url: str = ""


def select_releases(timeout: int = 30) -> list[ReleaseSelection]:
    records = _read_json_url(RELEASES_URL, timeout)
    if not isinstance(records, list):
        raise ValidationError("GitHub Releases response is not a list")
    candidates: list[ReleaseSelection] = []
    for record in records:
        if not isinstance(record, dict) or record.get("draft"):
            continue
        try:
            version = parse_semver(str(record.get("tag_name", "")))
        except ValidationError:
            continue
        version_text = str(record["tag_name"]).removeprefix("v")
        raw_assets = record.get("assets", [])
        if not isinstance(raw_assets, list):
            continue
        assets = {
            asset.get("name"): asset.get("browser_download_url")
            for asset in raw_assets
            if isinstance(asset, dict) and isinstance(asset.get("name"), str)
        }
        zip_name = f"vision-{version_text}.zip"
        if zip_name in assets and "SHA256SUMS" in assets:
            candidates.append(
                ReleaseSelection(
                    version_text,
                    version,
                    zip_name,
                    str(assets[zip_name]),
                    str(assets["SHA256SUMS"]),
                    record.get("body") if isinstance(record.get("body"), str) else "",
                    record.get("html_url")
                    if isinstance(record.get("html_url"), str)
                    else "",
                )
            )
    if not candidates:
        raise ValidationError("no release has both the universal ZIP and SHA256SUMS")
    return sorted(candidates, key=lambda item: item.version, reverse=True)


def select_latest(timeout: int = 30) -> ReleaseSelection:
    return select_releases(timeout)[0]


def summarize_release_notes(text: str, *, max_length: int = 600) -> str:
    """Render a compact plain-text summary from a GitHub release body."""

    fragments: list[str] = []
    in_code_block = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block or not line or line.startswith("<!--"):
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line)
        line = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        if line:
            fragments.append(line)

    summary = " ".join(fragments).strip()
    if not summary:
        return "No release notes were provided."
    if len(summary) <= max_length:
        return summary
    if max_length <= 1:
        return "…"[:max_length]
    truncated = summary[: max_length - 1].rstrip()
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0].rstrip()
    return f"{truncated}…"


def acquire(selection: ReleaseSelection, timeout: int = 60) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary = tempfile.TemporaryDirectory(prefix="vision-release-")
    root = Path(temporary.name)
    try:
        archive = root / selection.zip_name
        archive.write_bytes(_read_url(selection.zip_url, timeout))
        checksum_text = _read_url(selection.checksums_url, timeout).decode("ascii")
        expected = _checksum_for(checksum_text, selection.zip_name)
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual != expected:
            raise ValidationError("release ZIP checksum mismatch")
        extraction = root / "extracted"
        extraction.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            names = [member.filename for member in members]
            if len(names) != len(set(names)):
                raise ValidationError("release ZIP contains duplicate members")
            if sum(member.file_size for member in members) > 100 * 1024 * 1024:
                raise ValidationError("release ZIP exceeds the uncompressed size limit")
            for member in members:
                _validate_member(member)
            bundle.extractall(extraction)
        package = extraction / "vision"
        if not package.is_dir():
            raise ValidationError("release ZIP lacks vision package root")
        return temporary, package
    except Exception:
        temporary.cleanup()
        raise


def _read_json_url(url: str, timeout: int) -> object:
    try:
        return json.loads(_read_url(url, timeout))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValidationError(f"invalid JSON response from {url}: {error}") from error


def _read_url(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "vision-runtime"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (OSError, urllib.error.URLError) as error:
        raise ValidationError(f"network request failed for {url}: {error}") from error


def _checksum_for(text: str, filename: str) -> str:
    matches = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == filename:
            matches.append(parts[0].lower())
    if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0]):
        raise ValidationError(f"SHA256SUMS lacks one valid entry for {filename}")
    return matches[0]


def _validate_member(member: zipfile.ZipInfo) -> None:
    name = member.filename
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationError(f"unsafe ZIP member: {name}")
    if not (normalized == "vision" or normalized.startswith("vision/")):
        raise ValidationError(f"ZIP member outside package root: {name}")
    file_type = (member.external_attr >> 16) & 0o170000
    if file_type == 0o120000:
        raise ValidationError(f"release ZIP contains a symlink: {name}")
    if file_type not in {0, 0o040000, 0o100000}:
        raise ValidationError(f"release ZIP contains a special filesystem entry: {name}")
