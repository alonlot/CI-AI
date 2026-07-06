"""Configuration for the AI review job, all via environment variables."""

import os


class Config:
    def __init__(self) -> None:
        # Claude agent
        self.model = os.environ.get("AI_REVIEW_MODEL", "")  # empty = CLI default
        self.max_turns = int(os.environ.get("AI_REVIEW_MAX_TURNS", "50"))
        # When set, run with --dangerously-skip-permissions instead of a
        # read-only tool allowlist. Only do this if you trust every PR author.
        self.unrestricted = os.environ.get("AI_REVIEW_UNRESTRICTED", "") == "1"

        # Skills
        self.builtin_skills_dir = os.environ.get("AI_REVIEW_BUILTIN_SKILLS_DIR", "")
        # Comma-separated extra skill dirs (absolute or repo-relative)
        self.extra_skills_dirs = [
            d.strip()
            for d in os.environ.get("AI_REVIEW_SKILLS_DIRS", "").split(",")
            if d.strip()
        ]
        # Dir inside the reviewed repo that is always picked up if present
        self.repo_skills_dir = os.environ.get(
            "AI_REVIEW_REPO_SKILLS_DIR", ".ai-review/skills"
        )

        # Diff filtering
        # Extra ignore globs on top of the defaults, comma-separated
        self.extra_ignore = [
            g.strip()
            for g in os.environ.get("AI_REVIEW_IGNORE", "").split(",")
            if g.strip()
        ]
        # Repo-local ignore file (one glob per line)
        self.repo_ignore_file = os.environ.get(
            "AI_REVIEW_REPO_IGNORE_FILE", ".ai-review/ignore"
        )

        # Review behavior
        self.max_findings = int(os.environ.get("AI_REVIEW_MAX_FINDINGS", "15"))
        # Feed the MR's existing comments to the reviewer so it doesn't
        # repeat points already made (by humans or previous runs). On by
        # default; disable with AI_REVIEW_CONTEXT_NOTES=0.
        self.context_notes = os.environ.get("AI_REVIEW_CONTEXT_NOTES", "1") == "1"
        self.repo_dir = os.environ.get("AI_REVIEW_REPO_DIR", os.getcwd())
        # Second agent pass that tries to refute each finding (fewer false
        # positives, roughly doubles agent cost). On by default.
        self.verify = os.environ.get("AI_REVIEW_VERIFY", "1") == "1"
        # Merge gate: fail the job when verdict is request_changes or any
        # finding is at/above this severity. "" (default) = never fail,
        # otherwise one of: low | medium | high
        self.fail_on = os.environ.get("AI_REVIEW_FAIL_ON", "").strip().lower()
        # Post nothing, just print (useful when trying the job out)
        self.dry_run = os.environ.get("AI_REVIEW_DRY_RUN", "") == "1"
