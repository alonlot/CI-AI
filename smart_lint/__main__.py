"""Entrypoint: python3 -m smart_lint

Diff-only skill lint: no repo agent, no platform API tokens — just the diff,
the skill rule files, and one Claude API call. Prints every violation and
exits non-zero when there are any (unless SMART_LINT_WARN_ONLY=1).

Reuses ai_review's git/skills/ignore plumbing so skills are linked exactly
the same way as in the review job.
"""

import sys

from ai_review import gitops, ignore
from ai_review.skills import load_skills

from .config import Config, resolve_target_branch
from .linter import lint


def main() -> int:
    cfg = Config()

    target = resolve_target_branch(cfg)
    target_ref = gitops.ensure_target_branch(cfg.repo_dir, target)
    base_sha = gitops.merge_base(cfg.repo_dir, target_ref)

    all_files = gitops.changed_files(cfg.repo_dir, base_sha)
    files, skipped = ignore.filter_files(all_files, ignore.load_patterns(cfg))
    if skipped:
        print(f"[smart-lint] ignoring {len(skipped)} generated/vendored file(s)")
    if not files:
        print("[smart-lint] no lintable changed files, nothing to do")
        return 0
    diff = gitops.diff_text(cfg.repo_dir, base_sha, files)

    skills = load_skills(cfg)
    if not skills:
        print("[smart-lint] no skills found — nothing to lint against. "
              "Add rule .md files (see README).")
        return 0
    print(f"[smart-lint] linting {len(files)} file(s) against "
          f"{len(skills)} skill(s): {', '.join(n for n, _ in skills)}")

    violations = lint(cfg, skills, diff)

    if not violations:
        print("[smart-lint] ✓ no violations")
        return 0

    print(f"\n[smart-lint] ✖ {len(violations)} violation(s):\n")
    for v in violations:
        print(f"  ✖ [{v['skill']}] {v['path']}:{v['line']}")
        print(f"      rule:   {v['rule']}")
        print(f"      detail: {v['detail']}\n")

    if cfg.warn_only:
        print("[smart-lint] SMART_LINT_WARN_ONLY=1 — not failing the job")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
