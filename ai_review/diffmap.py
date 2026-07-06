"""Map which new-side lines of the diff can carry an inline comment.

Both GitLab and GitHub only accept inline comments on lines that appear in
the diff hunks (added or context lines on the new side). The agent sometimes
points slightly off, so instead of discovering that via a failed API call we
validate up front: keep the line if it's commentable, snap it to the nearest
changed line when it's close, otherwise fold the finding into the summary.
"""

import re

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
NEW_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+)$")


def build_line_index(diff_text: str) -> dict[str, dict[str, set[int]]]:
    """Return {path: {"all": commentable new-side lines, "added": added lines}}."""
    index: dict[str, dict[str, set[int]]] = {}
    current: dict[str, set[int]] | None = None
    new_line = 0
    in_hunk = False

    for raw in diff_text.splitlines():
        m = NEW_FILE_RE.match(raw)
        if m:
            path = m.group(1).strip()
            if path == "/dev/null":
                current = None
            else:
                current = index.setdefault(path, {"all": set(), "added": set()})
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
            current["all"].add(new_line)
            current["added"].add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            pass  # old side only
        elif raw.startswith("\\"):
            pass  # "\ No newline at end of file"
        else:
            current["all"].add(new_line)  # context line
            new_line += 1

    return index


def snap_line(index: dict[str, dict[str, set[int]]], path: str, line: int,
              tolerance: int = 10) -> int:
    """Best commentable line for a finding, or 0 to fold it into the summary."""
    info = index.get(path)
    if not info or not info["all"]:
        return 0
    if line in info["all"]:
        return line
    candidates = info["added"] or info["all"]
    nearest = min(candidates, key=lambda candidate: abs(candidate - line))
    if abs(nearest - line) <= tolerance:
        return nearest
    return 0
