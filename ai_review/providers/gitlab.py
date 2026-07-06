"""GitLab: posts an MR summary note + inline discussions on the diff.

Re-runs update the previous summary note in place and skip inline findings
that were already posted, so pushing new commits doesn't spam the MR.
"""

import os

import requests

from .base import (FINDING_KEY_RE, SUMMARY_MARKER, MergeRequestContext,
                   Provider, finding_body_md, finding_key, summary_body_md)


class GitLabProvider(Provider):
    name = "gitlab"

    def __init__(self) -> None:
        self.api = os.environ["CI_API_V4_URL"]
        self.project_id = os.environ["CI_PROJECT_ID"]
        self.mr_iid = os.environ["CI_MERGE_REQUEST_IID"]
        token = os.environ.get("GITLAB_TOKEN") or os.environ.get("AI_REVIEW_GITLAB_TOKEN")
        if not token:
            raise RuntimeError(
                "GITLAB_TOKEN is not set. Add a project access token with "
                "'api' scope as a CI/CD variable named GITLAB_TOKEN."
            )
        self.session = requests.Session()
        self.session.headers["PRIVATE-TOKEN"] = token
        self._mr = None

    def _mr_url(self, suffix: str = "") -> str:
        return (f"{self.api}/projects/{self.project_id}"
                f"/merge_requests/{self.mr_iid}{suffix}")

    def _paged_get(self, url: str) -> list[dict]:
        items: list[dict] = []
        page = "1"
        while page:
            r = self.session.get(url, params={"per_page": 100, "page": page})
            r.raise_for_status()
            items.extend(r.json())
            page = r.headers.get("X-Next-Page", "")
        return items

    def _get_mr(self) -> dict:
        if self._mr is None:
            r = self.session.get(self._mr_url())
            r.raise_for_status()
            self._mr = r.json()
        return self._mr

    def context(self) -> MergeRequestContext:
        mr = self._get_mr()
        return MergeRequestContext(
            target_branch=os.environ.get(
                "CI_MERGE_REQUEST_TARGET_BRANCH_NAME", mr["target_branch"]
            ),
            title=mr.get("title", ""),
            description=mr.get("description") or "",
        )

    def existing_feedback(self) -> list[dict]:
        feedback: list[dict] = []
        for disc in self._paged_get(self._mr_url("/discussions")):
            for note in disc.get("notes", []):
                if note.get("system"):
                    continue  # "changed the description", pipeline events, ...
                body = (note.get("body") or "").strip()
                if not body:
                    continue
                position = note.get("position") or {}
                feedback.append({
                    "author": (note.get("author") or {}).get("username", "?"),
                    "body": body,
                    "path": position.get("new_path"),
                    "line": position.get("new_line"),
                    "resolved": bool(note.get("resolved")),
                })
        return feedback

    def _existing_finding_keys(self) -> set[str]:
        keys: set[str] = set()
        for disc in self._paged_get(self._mr_url("/discussions")):
            for note in disc.get("notes", []):
                keys.update(FINDING_KEY_RE.findall(note.get("body") or ""))
        return keys

    def _existing_summary_note_id(self) -> int | None:
        for note in self._paged_get(self._mr_url("/notes")):
            if SUMMARY_MARKER in (note.get("body") or ""):
                return note["id"]
        return None

    def post_review(self, summary_md: str, findings: list[dict],
                    head_sha: str) -> None:
        diff_refs = self._get_mr()["diff_refs"]
        already_posted = self._existing_finding_keys()

        folded: list[dict] = []
        posted = skipped = 0
        for f in findings:
            if finding_key(f) in already_posted:
                skipped += 1
                continue
            if f["line"] <= 0 or not self._post_inline(f, diff_refs):
                folded.append(f)
            else:
                posted += 1

        body = summary_body_md(summary_md, folded)
        note_id = self._existing_summary_note_id()
        if note_id:
            r = self.session.put(self._mr_url(f"/notes/{note_id}"),
                                 json={"body": body})
        else:
            r = self.session.post(self._mr_url("/notes"), json={"body": body})
        r.raise_for_status()
        print(f"[ai-review] MR !{self.mr_iid}: summary "
              f"{'updated' if note_id else 'posted'}, {posted} inline, "
              f"{skipped} already present, {len(folded)} folded into summary")

    def _post_inline(self, finding: dict, diff_refs: dict) -> bool:
        payload = {
            "body": finding_body_md(finding),
            "position": {
                "position_type": "text",
                "base_sha": diff_refs["base_sha"],
                "head_sha": diff_refs["head_sha"],
                "start_sha": diff_refs["start_sha"],
                "new_path": finding["path"],
                "new_line": finding["line"],
            },
        }
        r = self.session.post(self._mr_url("/discussions"), json=payload)
        if r.ok:
            return True
        print(f"[ai-review] inline comment failed for "
              f"{finding['path']}:{finding['line']} ({r.status_code}), "
              f"folding into summary")
        return False
