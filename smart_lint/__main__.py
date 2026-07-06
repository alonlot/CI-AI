"""Entrypoint: python3 -m smart_lint

Diff-only skill lint: no repo agent, no platform API tokens — just the diff,
the skill rule files, and Claude API calls. Prints every violation and exits
non-zero when there are any (unless SMART_LINT_WARN_ONLY=1).

Large diffs are linted in per-file batches (SMART_LINT_BATCH_CHARS per call)
so nothing is ever truncated. Developers can suppress a rule on a specific
line with a `lint-ok: <reason>` comment on (or right above) that line.

Reuses ai_review's git/skills/ignore plumbing so skills are linked exactly
the same way as in the review job.
"""

import sys
from collections import defaultdict

import anthropic

from ai_review import gitops, ignore
from ai_review.skills import load_skills

from . import difftools
from .config import Config, resolve_target_branch
from .linter import lint_batch, render_rules
from .log import Section, bold, green, red, yellow


def main() -> int:
    cfg = Config()

    # ---- collect the diff -------------------------------------------------
    target = resolve_target_branch(cfg)
    target_ref = gitops.ensure_target_branch(cfg.repo_dir, target)
    base_sha = gitops.merge_base(cfg.repo_dir, target_ref)

    all_files = gitops.changed_files(cfg.repo_dir, base_sha)
    files, skipped = ignore.filter_files(all_files, ignore.load_patterns(cfg))
    if not files:
        print(f"smart-lint: no lintable changed files vs {target} — "
              f"{green('PASS')}")
        return 0
    diff = gitops.diff_text(cfg.repo_dir, base_sha, files, max_chars=None)

    skills = load_skills(cfg)
    if not skills:
        print("smart-lint: no skill rule files found — nothing to lint "
              "against. Add .md files (see README). PASS (vacuously)")
        return 0

    with Section("lint_setup", "smart-lint: what is being checked"):
        print(f"diffing against : {target} (merge-base {base_sha[:10]})")
        print(f"files to lint   : {len(files)}")
        for f in files:
            print(f"  - {f}")
        if skipped:
            print(f"ignored files   : {len(skipped)} (generated/vendored)")
            for f in skipped:
                print(f"  - {f}")
        print(f"rule skills     : {', '.join(n for n, _ in skills)}")
        print(f"model           : {cfg.model}")

    # ---- lint, in batches ---------------------------------------------
    file_diffs = difftools.split_by_file(diff)
    batches = difftools.pack_batches(file_diffs, cfg.batch_chars)
    rules_block = render_rules(skills)
    client = anthropic.Anthropic()

    violations: list[dict] = []
    suppressed: list[dict] = []
    tokens_in = tokens_out = 0

    with Section("lint_run", f"smart-lint: linting {len(batches)} batch(es)"):
        for i, batch in enumerate(batches, 1):
            batch_diff = "".join(text for _, text in batch)
            print(f"batch {i}/{len(batches)}: {len(batch)} file(s), "
                  f"{len(batch_diff):,} chars ...", flush=True)
            result = lint_batch(cfg, rules_block, batch_diff, client)
            print(f"  -> {len(result.violations)} violation(s), "
                  f"{len(result.suppressed)} suppressed, "
                  f"tokens {result.input_tokens:,}/{result.output_tokens:,}")
            violations.extend(result.violations)
            suppressed.extend(result.suppressed)
            tokens_in += result.input_tokens
            tokens_out += result.output_tokens

    # backstop: drop anything the model reported despite a lint-ok comment
    line_texts = difftools.new_line_texts(diff)
    missed = [v for v in violations if difftools.is_suppressed(line_texts, v)]
    if missed:
        violations = [v for v in violations if v not in missed]
        for v in missed:
            suppressed.append({**v, "reason": "(lint-ok comment on the line)"})

    # ---- report --------------------------------------------------------
    if suppressed:
        with Section("lint_suppressed",
                     f"smart-lint: {len(suppressed)} suppressed by lint-ok"):
            for s in suppressed:
                print(f"  {yellow('~')} [{s['skill']}] {s['path']}:{s['line']} "
                      f"— {s['rule']}")
                print(f"      developer reason: {s.get('reason', '')}")

    print()
    if not violations:
        print(f"{green('✓ smart-lint PASS')} — {len(files)} file(s) clean "
              f"against {len(skills)} skill(s) "
              f"(tokens {tokens_in:,}/{tokens_out:,})")
        return 0

    by_file: dict[str, list[dict]] = defaultdict(list)
    for v in violations:
        by_file[v["path"]].append(v)

    print(red(f"✖ smart-lint found {len(violations)} violation(s) "
              f"in {len(by_file)} file(s)") + "\n")
    for path in sorted(by_file):
        print(bold(path))
        for v in sorted(by_file[path], key=lambda v: v["line"]):
            print(f"  {red('✖')} line {v['line']:<5} [{v['skill']}]  {v['rule']}")
            print(f"      {v['detail']}")
        print()

    print("To suppress a finding intentionally, add a comment on (or right "
          "above) the line:  lint-ok: <why this is fine>")
    print(f"(tokens used: {tokens_in:,} in / {tokens_out:,} out)")

    if cfg.warn_only:
        print(f"\n{yellow('SMART_LINT_WARN_ONLY=1 — reporting only, job passes')}")
        return 0
    print(f"\n{red('RESULT: FAIL')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
