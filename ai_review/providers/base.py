"""Provider interface: everything platform-specific lives behind this."""

import hashlib
import re
from abc import ABC, abstractmethod

# Markers embedded in posted comments so re-runs can find and update/skip
# them instead of spamming the MR with duplicates.
SUMMARY_MARKER = "<!-- ai-review-bot:summary -->"
FINDING_KEY_RE = re.compile(r"<!-- ai-review-bot:finding:([0-9a-f]{12}) -->")


def finding_key(finding: dict) -> str:
    """Stable identity of a finding across runs (same file + same title)."""
    raw = f"{finding['path']}:{finding['title']}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def finding_body_md(finding: dict) -> str:
    return (f"<!-- ai-review-bot:finding:{finding_key(finding)} -->\n"
            f"**🤖 [{finding['severity']}] {finding['title']}**\n\n"
            f"{finding['body']}")


def summary_body_md(summary_md: str, folded: list[dict]) -> str:
    body = f"{SUMMARY_MARKER}\n## 🤖 AI Code Review\n\n{summary_md}"
    if folded:
        body += "\n\n### Additional findings\n"
        for f in folded:
            body += (f"\n- **[{f['severity']}] {f['path']}:{f['line']}** — "
                     f"{f['title']}\n  {f['body']}")
    return body


class MergeRequestContext:
    """What the review needs to know about the MR/PR being reviewed."""

    def __init__(self, target_branch: str, title: str = "", description: str = ""):
        self.target_branch = target_branch
        self.title = title
        self.description = description


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    def context(self) -> MergeRequestContext:
        """Read the MR/PR metadata from the CI environment / API."""

    @abstractmethod
    def post_review(self, summary_md: str, findings: list[dict],
                    head_sha: str) -> None:
        """Post the summary and the inline findings.

        Contract for implementations:
        - findings with ``line <= 0`` go into the summary, not inline
        - update the previous run's summary comment in place (SUMMARY_MARKER)
        - skip inline findings already posted by a previous run (finding_key)
        - if an inline comment can't be placed, fold it into the summary
          instead of failing the job
        """
