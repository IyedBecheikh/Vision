#!/usr/bin/env python3
"""Regenerate Codex worker TOMLs from the canonical worker store.

The canonical instruction body for each role lives in ``vision/workers/``. This
developer tool renders the Codex representation so the two platform backends
cannot drift. It is not part of the release payload.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vision"))
sys.path.insert(0, str(ROOT / "vision" / "runtime"))

from runtime.platform_settings import MODEL_TARGETS  # noqa: E402
from runtime.workers import load_worker_specs, render_codex_worker  # noqa: E402


def main() -> int:
    workers_dir = ROOT / "vision" / "workers"
    agents_dir = ROOT / "vision" / "agents"
    specs = load_worker_specs(workers_dir, None)
    if not specs:
        print("no canonical workers found", file=sys.stderr)
        return 1
    for role in sorted(specs):
        spec = specs[role]
        model = MODEL_TARGETS.get(spec.model_target, MODEL_TARGETS["luna"])
        rendered = render_codex_worker(spec, model=model)
        (agents_dir / f"{role}.toml").write_text(rendered, encoding="utf-8")
        print(f"rendered {role}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
