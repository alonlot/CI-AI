"""Entrypoint: python3 -m ai_review

Flow:
  1. detect CI platform (GitLab / GitHub) and read MR/PR metadata
  2. fetch the target branch, compute merge-base + diff (noise filtered out)
  3. load skills (built-in + repo-local .md files)
  4. run the Claude Code agent headlessly over the checkout
  5. adversarially verify the findings (second agent pass)
  6. snap finding lines to commentable diff lines
  7. post/update the summary + inline findings on the MR/PR
  8. optionally fail the job (merge gate) based on AI_REVIEW_FAIL_ON
"""

import sys

from . import diffmap, gitops, ignore
from .agent import (ReviewResult, build_prompt, render_existing_feedback,
                    run_agent, verify_findings)
from .config import Config
from .providers import detect_provider
from .skills import load_skills, render_skills

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}


def main() -> int:
    cfg = Config()
    provider = detect_provider()
    print(f"[ai-review] provider: {provider.name}")

    ctx = provider.context()
    target_ref = gitops.ensure_target_branch(cfg.repo_dir, ctx.target_branch)
    base_sha = gitops.merge_base(cfg.repo_dir, target_ref)
    head = gitops.head_sha(cfg.repo_dir)

    all_files = gitops.changed_files(cfg.repo_dir, base_sha)
    patterns = ignore.load_patterns(cfg)
    files, skipped_files = ignore.filter_files(all_files, patterns)
    if skipped_files:
        print(f"[ai-review] ignoring {len(skipped_files)} generated/vendored "
              f"file(s): {', '.join(skipped_files[:8])}"
              f"{' ...' if len(skipped_files) > 8 else ''}")
    if not files:
        print("[ai-review] no reviewable changed files, nothing to do")
        return 0

    diff = gitops.diff_text(cfg.repo_dir, base_sha, files)
    print(f"[ai-review] reviewing {len(files)} changed files "
          f"({base_sha[:10]}..{head[:10]})")

    skills = load_skills(cfg)
    print(f"[ai-review] skills loaded: {', '.join(n for n, _ in skills) or '(none)'}")

    feedback_block = ""
    if cfg.context_notes:
        existing = provider.existing_feedback()
        feedback_block = render_existing_feedback(existing)
        if existing:
            print(f"[ai-review] {len(existing)} existing comment(s) given to "
                  f"the reviewer as do-not-repeat context")

    prompt = build_prompt(cfg, base_sha, head, files, diff,
                          render_skills(skills), feedback_block)
    if ctx.title:
        prompt = (f"Merge request title: {ctx.title}\n"
                  f"Description:\n{ctx.description}\n\n{prompt}")

    review = run_agent(cfg, prompt)
    print(f"[ai-review] verdict: {review.verdict}, "
          f"{len(review.findings)} finding(s)")

    if cfg.verify and review.findings:
        review.findings = verify_findings(cfg, review.findings)
        print(f"[ai-review] {len(review.findings)} finding(s) after verification")

    line_index = diffmap.build_line_index(diff)
    for f in review.findings:
        snapped = diffmap.snap_line(line_index, f["path"], f["line"])
        if snapped != f["line"]:
            print(f"[ai-review] {f['path']}:{f['line']} -> "
                  f"{snapped if snapped else 'summary'} ('{f['title']}')")
        f["line"] = snapped

    if cfg.dry_run:
        print("[ai-review] dry run — not posting. Review:")
        print(review.summary)
        for f in review.findings:
            print(f"  [{f['severity']}] {f['path']}:{f['line']} {f['title']}")
    else:
        provider.post_review(review.summary, review.findings, head)

    return 1 if _gate_fails(cfg, review) else 0


def _gate_fails(cfg: Config, review: ReviewResult) -> bool:
    if cfg.fail_on not in SEVERITY_RANK:
        return False
    threshold = SEVERITY_RANK[cfg.fail_on]
    worst = max((SEVERITY_RANK.get(f["severity"], 0) for f in review.findings),
                default=0)
    if review.verdict == "request_changes" or worst >= threshold:
        print(f"[ai-review] merge gate: failing job "
              f"(fail_on={cfg.fail_on}, verdict={review.verdict})")
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
