"""Diff utilities for smart-lint: per-file splitting, batch packing, and the
line-text map used to enforce `lint-ok` suppressions."""

import re

from ai_review.diffmap import HUNK_RE, NEW_FILE_RE

FILE_HEADER_RE = re.compile(r'^diff --git (?:"?a/.*"? )?"?b/(.+?)"?$')


def split_by_file(diff: str) -> list[tuple[str, str]]:
    """Split a unified diff into (path, file_diff) pieces."""
    pieces: list[tuple[str, str]] = []
    path: str | None = None
    lines: list[str] = []
    for line in diff.splitlines(keepends=True):
        m = FILE_HEADER_RE.match(line.rstrip("\n"))
        if m:
            if path is not None:
                pieces.append((path, "".join(lines)))
            path, lines = m.group(1), [line]
        elif path is not None:
            lines.append(line)
    if path is not None:
        pieces.append((path, "".join(lines)))
    return pieces


def pack_batches(file_diffs: list[tuple[str, str]],
                 budget_chars: int) -> list[list[tuple[str, str]]]:
    """Greedily pack per-file diffs into batches under the char budget.

    A single file larger than the budget still gets its own batch — nothing
    is ever truncated or dropped.
    """
    batches: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    size = 0
    for path, text in file_diffs:
        if current and size + len(text) > budget_chars:
            batches.append(current)
            current, size = [], 0
        current.append((path, text))
        size += len(text)
    if current:
        batches.append(current)
    return batches


def new_line_texts(diff: str) -> dict[str, dict[int, str]]:
    """{path: {new-side line number: line text}} for all lines in hunks."""
    texts: dict[str, dict[int, str]] = {}
    current: dict[int, str] | None = None
    new_line = 0
    in_hunk = False

    for raw in diff.splitlines():
        m = NEW_FILE_RE.match(raw)
        if m:
            path = m.group(1).strip()
            current = None if path == "/dev/null" else texts.setdefault(path, {})
            in_hunk = False
            continue
        m = HUNK_RE.match(raw)
        if m:
            new_line = int(m.group(1))
            in_hunk = current is not None
            continue
        if not in_hunk or current is None:
            continue
        if raw.startswith("+"):
            current[new_line] = raw[1:]
            new_line += 1
        elif raw.startswith("-") or raw.startswith("\\"):
            pass
        else:
            current[new_line] = raw[1:] if raw else ""
            new_line += 1

    return texts


SUPPRESS_RE = re.compile(r"lint-ok\s*:\s*\S", re.IGNORECASE)


def is_suppressed(texts: dict[str, dict[int, str]], violation: dict) -> bool:
    """True when the violating line (or the line above) carries a
    ``lint-ok: <reason>`` comment. Backstop for the model missing one."""
    file_lines = texts.get(violation["path"], {})
    for line_no in (violation["line"], violation["line"] - 1):
        if SUPPRESS_RE.search(file_lines.get(line_no, "")):
            return True
    return False
