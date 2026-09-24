#!/usr/bin/env python3
"""Shared entry point for the deployment token report.

Selects a platform backend without embedding platform conditionals in either
implementation. The default backend is Codex so existing invocations keep their
behavior; pass ``--platform opencode`` to use the OpenCode session backend.
"""

from __future__ import annotations

import argparse
import sys

PLATFORMS = ("codex", "opencode")


def _select_backend(platform: str):
    if platform == "opencode":
        import report_tokens_opencode as backend

        return backend
    import report_tokens_codex as backend

    return backend


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    selector = argparse.ArgumentParser(add_help=False)
    selector.add_argument("--platform", choices=PLATFORMS, default="codex")
    known, remaining = selector.parse_known_args(arguments)
    backend = _select_backend(known.platform)
    return backend.main(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
