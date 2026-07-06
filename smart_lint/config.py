"""Configuration for smart-lint, all via environment variables.

Skill discovery works exactly like ai_review (this object is duck-typed to
ai_review.skills.load_skills): built-in dir baked into the image, extra dirs
via env, plus a dir inside the linted repo itself.
"""

import os


class Config:
    def __init__(self) -> None:
        self.model = os.environ.get("SMART_LINT_MODEL", "claude-opus-4-8")
        self.max_tokens = int(os.environ.get("SMART_LINT_MAX_TOKENS", "16000"))

        # Skill discovery (same mechanism/attrs as ai_review.skills expects)
        self.builtin_skills_dir = os.environ.get(
            "SMART_LINT_BUILTIN_SKILLS_DIR",
            os.environ.get("AI_REVIEW_BUILTIN_SKILLS_DIR", ""),
        )
        self.extra_skills_dirs = [
            d.strip()
            for d in os.environ.get("SMART_LINT_SKILLS_DIRS", "").split(",")
            if d.strip()
        ]
        self.repo_skills_dir = os.environ.get(
            "SMART_LINT_REPO_SKILLS_DIR", ".smart-lint/skills"
        )

        # Diff
        self.repo_dir = os.environ.get("SMART_LINT_REPO_DIR", os.getcwd())
        # Explicit override; otherwise resolved from CI env (MR target branch)
        self.target_branch = os.environ.get("SMART_LINT_TARGET_BRANCH", "")
        self.extra_ignore = [
            g.strip()
            for g in os.environ.get("SMART_LINT_IGNORE",
                                    os.environ.get("AI_REVIEW_IGNORE", "")).split(",")
            if g.strip()
        ]
        self.repo_ignore_file = os.environ.get(
            "SMART_LINT_REPO_IGNORE_FILE", ".ai-review/ignore"
        )

        # Report violations but always exit 0
        self.warn_only = os.environ.get("SMART_LINT_WARN_ONLY", "") == "1"


def resolve_target_branch(cfg: Config) -> str:
    if cfg.target_branch:
        return cfg.target_branch
    # GitLab MR pipelines / GitHub pull_request events
    for var in ("CI_MERGE_REQUEST_TARGET_BRANCH_NAME", "GITHUB_BASE_REF"):
        value = os.environ.get(var)
        if value:
            return value
    return "main"
