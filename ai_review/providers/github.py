"""GitHub: summary as an issue comment (updated in place across runs) and
findings as individual PR review comments (deduped by finding key)."""

import json
import os

import requests

from .base import (FINDING_KEY_RE, SUMMARY_MARKER, MergeRequestContext,
                   Provider, finding_body_md, finding_key, summary_body_md)


class GitHubProvider(Provider):
    name = "github"

    def __init__(self) -> None:
        self.repo = os.environ["GITHUB_REPOSITORY"]  # owner/name
        self.api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("AI_REVIEW_GITHUB_TOKEN")
        if not token:
            raise RuntimeError("GITHUB_TOKEN is not set.")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        })
        self.pr_number = self._pr_number()
        self._pr = None

    def _pr_number(self) -> int:
        event_path = os.environ.get("GITHUB_EVENT_PATH")
        if event_path and os.path.exists(event_path):
            with open(event_path, encoding="utf-8") as f:
                event = json.load(f)
            if "pull_request" in event:
                return int(event["pull_request"]["number"])
        ref = os.environ.get("GITHUB_REF", "")  # refs/pull/123/merge
        parts = ref.split("/")
        if len(parts) >= 3 and parts[1] == "pull":
            return int(parts[2])
        raise RuntimeError("Could not determine PR number "
                           "(run this job on pull_request events).")

    def _paged_get(self, url: str) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            r = self.session.get(url, params={"per_page": 100, "page": page})
            r.raise_for_status()
            batch = r.json()
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1

    def _get_pr(self) -> dict:
        if self._pr is None:
            r = self.session.get(
                f"{self.api}/repos/{self.repo}/pulls/{self.pr_number}")
            r.raise_for_status()
            self._pr = r.json()
        return self._pr

    def context(self) -> MergeRequestContext:
        pr = self._get_pr()
        return MergeRequestContext(
            target_branch=pr["base"]["ref"],
            title=pr.get("title", ""),
            description=pr.get("body") or "",
        )

    def existing_feedback(self) -> list[dict]:
        feedback: list[dict] = []
        inline_url = f"{self.api}/repos/{self.repo}/pulls/{self.pr_number}/comments"
        for c in self._paged_get(inline_url):
            body = (c.get("body") or "").strip()
            if body:
                feedback.append({
                    "author": (c.get("user") or {}).get("login", "?"),
                    "body": body,
                    "path": c.get("path"),
                    "line": c.get("line") or c.get("original_line"),
                    "resolved": False,
                })
        issue_url = f"{self.api}/repos/{self.repo}/issues/{self.pr_number}/comments"
        for c in self._paged_get(issue_url):
            body = (c.get("body") or "").strip()
            if body:
                feedback.append({
                    "author": (c.get("user") or {}).get("login", "?"),
                    "body": body,
                    "path": None,
                    "line": None,
                    "resolved": False,
                })
        return feedback

    def _existing_finding_keys(self) -> set[str]:
        url = f"{self.api}/repos/{self.repo}/pulls/{self.pr_number}/comments"
        keys: set[str] = set()
        for comment in self._paged_get(url):
            keys.update(FINDING_KEY_RE.findall(comment.get("body") or ""))
        return keys

    def _existing_summary_comment_id(self) -> int | None:
        url = f"{self.api}/repos/{self.repo}/issues/{self.pr_number}/comments"
        for comment in self._paged_get(url):
            if SUMMARY_MARKER in (comment.get("body") or ""):
                return comment["id"]
        return None

    def post_review(self, summary_md: str, findings: list[dict],
                    head_sha: str) -> None:
        # On pull_request events the local checkout is the synthetic merge
        # commit; the review-comments API wants the PR head SHA instead.
        head_sha = self._get_pr()["head"]["sha"]
        already_posted = self._existing_finding_keys()

        folded: list[dict] = []
        posted = skipped = 0
        for f in findings:
            if finding_key(f) in already_posted:
                skipped += 1
                continue
            if f["line"] <= 0 or not self._post_inline(f, head_sha):
                folded.append(f)
            else:
                posted += 1

        body = summary_body_md(summary_md, folded)
        comment_id = self._existing_summary_comment_id()
        if comment_id:
            r = self.session.patch(
                f"{self.api}/repos/{self.repo}/issues/comments/{comment_id}",
                json={"body": body})
        else:
            r = self.session.post(
                f"{self.api}/repos/{self.repo}/issues/{self.pr_number}/comments",
                json={"body": body})
        r.raise_for_status()
        print(f"[ai-review] PR #{self.pr_number}: summary "
              f"{'updated' if comment_id else 'posted'}, {posted} inline, "
              f"{skipped} already present, {len(folded)} folded into summary")

    def _post_inline(self, finding: dict, head_sha: str) -> bool:
        url = f"{self.api}/repos/{self.repo}/pulls/{self.pr_number}/comments"
        r = self.session.post(url, json={
            "body": finding_body_md(finding),
            "commit_id": head_sha,
            "path": finding["path"],
            "line": finding["line"],
            "side": "RIGHT",
        })
        if r.ok:
            return True
        print(f"[ai-review] inline comment failed for "
              f"{finding['path']}:{finding['line']} ({r.status_code}), "
              f"folding into summary")
        return False
