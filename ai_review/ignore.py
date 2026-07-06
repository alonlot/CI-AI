"""Filter noise out of the reviewed diff.

Lockfiles, minified/generated assets, and vendored code burn tokens and
produce useless findings, so they are excluded from the diff the agent sees.
Repos can extend the list by adding globs to ``.ai-review/ignore`` (one per
line, ``#`` comments allowed) — same drop-in philosophy as skills.
"""

import fnmatch
import os

from .config import Config

DEFAULT_IGNORE = [
    # lockfiles
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "poetry.lock", "Pipfile.lock", "uv.lock",
    "Cargo.lock", "composer.lock", "Gemfile.lock", "go.sum", "*.lock",
    # minified / bundled / generated assets
    "*.min.js", "*.min.css", "*.map", "*.svg", "*.snap",
    "*_pb2.py", "*_pb2_grpc.py", "*.pb.go", "*.generated.*",
    # vendored / build output directories
    "node_modules/", "vendor/", "dist/", "build/", "out/",
    "__snapshots__/", ".yarn/",
]


def load_patterns(cfg: Config) -> list[str]:
    patterns = list(DEFAULT_IGNORE) + list(cfg.extra_ignore)
    repo_file = os.path.join(cfg.repo_dir, cfg.repo_ignore_file)
    if os.path.isfile(repo_file):
        with open(repo_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
    return patterns


def is_ignored(path: str, patterns: list[str]) -> bool:
    path = path.replace("\\", "/")
    segments = path.split("/")
    basename = segments[-1]
    for pat in patterns:
        if pat.endswith("/"):
            # directory pattern: matches if any path segment equals it
            if pat[:-1] in segments[:-1]:
                return True
        elif fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(basename, pat):
            return True
    return False


def filter_files(files: list[str], patterns: list[str]) -> tuple[list[str], list[str]]:
    """Split into (kept, skipped)."""
    kept, skipped = [], []
    for f in files:
        (skipped if is_ignored(f, patterns) else kept).append(f)
    return kept, skipped
