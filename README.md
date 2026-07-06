# AI Code Review CI Job

A generic, platform-agnostic CI job that runs a **Claude Code agent** over the
diff of a merge request / pull request and posts a code review back to
GitLab or GitHub — a summary note plus inline comments on the changed lines.

The agent gets the **full repository checkout**, not just the diff, so it can
read surrounding code, related modules, and git history to understand changes
in context.

```
CI runner clones repo
        │
        ▼
┌─────────────────────── Docker image ───────────────────────┐
│  python3 -m ai_review                                       │
│    1. detect platform (GitLab / GitHub) + read MR metadata  │
│    2. git fetch target branch → merge-base → diff           │
│       (lockfiles / generated / vendored files filtered out) │
│    3. load skills (*.md guideline files)                    │
│    4. claude -p  (headless agent, full repo read access)    │
│    5. second agent pass adversarially verifies findings     │
│    6. snap finding lines to commentable diff lines          │
│    7. POST/update summary + inline comments (no dup spam)   │
│    8. optional merge gate (fail job on severe findings)     │
└─────────────────────────────────────────────────────────────┘
```

## Layout

| Path | What |
|---|---|
| `Dockerfile` | Image: node + `@anthropic-ai/claude-code` CLI + python (serves both jobs) |
| `ai_review/` | The review orchestrator (entrypoint `python3 -m ai_review`) |
| `ai_review/providers/` | GitLab / GitHub adapters — add a provider here for another platform |
| `smart_lint/` | Diff-only skill lint (entrypoint `python3 -m smart_lint`), see below |
| `skills/` | Built-in review skills baked into the image |
| `ci-templates/` | Ready-to-copy `.gitlab-ci.yml` jobs & GitHub Actions workflow |

## Setup

1. **Build & push the image**

   ```sh
   docker build -t <registry>/ai-review:latest .
   docker push <registry>/ai-review:latest
   ```

2. **Add secrets**
   - `ANTHROPIC_API_KEY` — always required.
   - GitLab: `GITLAB_TOKEN` — project access token with `api` scope
     (needed to post MR notes; the built-in `CI_JOB_TOKEN` can't).
   - GitHub: the automatic `GITHUB_TOKEN` works (grant `pull-requests: write`).

3. **Add the job** — copy from [`ci-templates/`](ci-templates/). The job must
   run on merge-request / pull-request events with full git history
   (`GIT_DEPTH: 0` / `fetch-depth: 0`).

## Skills — how to extend the review

A *skill* is just a markdown file with review guidance. Every `*.md` file
found in the skill directories is injected into the reviewer's prompt, so
extending the review = dropping in a file. No code changes.

Discovery order (same-named later file overrides an earlier one):

1. `skills/` in this repo — baked into the image, applies to every project.
2. Dirs listed in `AI_REVIEW_SKILLS_DIRS` (comma-separated) — e.g. a shared
   "team standards" folder mounted or vendored into the pipeline.
3. `.ai-review/skills/` **inside the reviewed repo** — per-project rules,
   owned by that repo's team.

Example — add `.ai-review/skills/api-conventions.md` to a service repo:

```md
# API conventions
- All new endpoints must be versioned under /v2/.
- Response bodies use snake_case keys.
- Breaking changes to public DTOs require a CHANGELOG entry.
```

The agent is told to name the skill when a finding comes from one.

> The reviewed repo's own `CLAUDE.md` / `.claude/` directory is also picked up
> automatically by the Claude Code CLI, since the agent runs inside the
> checkout.

## Ignore list — keep noise out of the review

Lockfiles, minified/generated assets, and vendored directories are excluded
from the diff by default (see `ai_review/ignore.py`). Extend per repo with
`.ai-review/ignore` (one glob per line, `#` comments, `dir/` matches a
directory anywhere in the path), or per pipeline with `AI_REVIEW_IGNORE`
(comma-separated globs).

## The reviewer sees existing MR discussion

Before reviewing, the job fetches the comments already on the MR — from
humans **and** previous bot runs — and gives them to the reviewer as
do-not-repeat context. A point a colleague already made (even worded
differently, even on a nearby line) is skipped; resolved threads are only
re-raised if the current code clearly still has the problem. Disable with
`AI_REVIEW_CONTEXT_NOTES=0`.

## Re-runs don't spam the MR

Every posted comment carries a hidden marker. On the next pipeline run the
job **updates the existing summary comment in place** and **skips inline
findings that are already posted** (identity = file path + finding title).
Findings whose line isn't part of the diff are snapped to the nearest changed
line, or folded into the summary when nothing is close.

## Verification pass

After the review, a second headless agent call re-reads the code and tries to
*refute* each finding; refuted findings are dropped. This roughly doubles
agent cost but removes most false positives. Disable with `AI_REVIEW_VERIFY=0`.
If the verification call itself fails, all findings are kept (fails open).

## Smart lint (`smart_lint/`) — diff-only skill checker

A second, cheaper job in the same image: `python3 -m smart_lint`. Unlike the
review agent it **only looks at the diff** — one Claude API call, no repo
exploration, no GitLab/GitHub token (nothing is posted; it prints violations
and fails the job). Use it as a hard rule-check next to the advisory review.

Skills are linked **the same way** as the review job — every `*.md` rule file
found is a rule set:

1. built-in `skills/` from the image (override with `SMART_LINT_BUILTIN_SKILLS_DIR`)
2. dirs in `SMART_LINT_SKILLS_DIRS` (comma-separated)
3. `.smart-lint/skills/` inside the linted repo

Each violation is reported as `[skill] path:line` with the exact rule broken:

```
[smart-lint] ✖ 2 violation(s):

  ✖ [conventions] src/api/users.py:88
      rule:   Errors must not be silently swallowed
      detail: The new except block around fetch_user() passes without logging.
```

### Suppressing a finding

Add a comment with `lint-ok: <reason>` on the offending line (or the line
right above it) — the finding moves to a "suppressed" section of the log
instead of failing the job. A bare `lint-ok` without a reason does **not**
suppress; the reason is the point. Suppression is enforced twice: the model
is told the rule, and the job re-checks reported violations against the diff
text as a backstop.

```python
data = eval(raw)  # lint-ok: input is generated by our own config compiler
```

### Big diffs

Diffs are linted in per-file batches of at most `SMART_LINT_BATCH_CHARS`
(default 200k chars) per API call — nothing is ever truncated or dropped,
a huge MR just costs more calls. Batch progress and per-batch token usage
show up in the job log, and on GitLab the log is organized into collapsible
sections (setup / batches / suppressed / results).

| Variable | Default | Meaning |
|---|---|---|
| `SMART_LINT_MODEL` | `claude-opus-4-8` | model for the lint call |
| `SMART_LINT_SKILLS_DIRS` | — | extra rule dirs, comma-separated |
| `SMART_LINT_REPO_SKILLS_DIR` | `.smart-lint/skills` | in-repo rules dir |
| `SMART_LINT_TARGET_BRANCH` | auto (MR/PR target) | branch to diff against |
| `SMART_LINT_BATCH_CHARS` | `200000` | max diff chars per API call |
| `SMART_LINT_WARN_ONLY` | off | `1` → report violations but exit 0 |
| `SMART_LINT_IGNORE` | — | extra ignore globs (defaults shared with review) |

## Merge gate (optional)

By default the job is advisory. Set `AI_REVIEW_FAIL_ON=high` (or `medium` /
`low`) to make it exit non-zero when the verdict is `request_changes` or any
finding is at/above that severity — and remove `allow_failure: true` /
`continue-on-error: true` from the CI job so the failure actually blocks.

## Configuration (env vars)

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | required |
| `AI_REVIEW_MODEL` | CLI default | model override, e.g. `claude-opus-4-8` |
| `AI_REVIEW_MAX_TURNS` | `50` | agent turn cap |
| `AI_REVIEW_MAX_FINDINGS` | `15` | max inline findings |
| `AI_REVIEW_SKILLS_DIRS` | — | extra skill dirs, comma-separated |
| `AI_REVIEW_REPO_SKILLS_DIR` | `.ai-review/skills` | in-repo skills dir |
| `AI_REVIEW_IGNORE` | — | extra ignore globs, comma-separated |
| `AI_REVIEW_REPO_IGNORE_FILE` | `.ai-review/ignore` | in-repo ignore file |
| `AI_REVIEW_VERIFY` | on | `0` → skip the finding-verification pass |
| `AI_REVIEW_CONTEXT_NOTES` | on | `0` → don't feed existing MR comments to the reviewer |
| `AI_REVIEW_FAIL_ON` | — | `low`/`medium`/`high` → merge gate (see above) |
| `AI_REVIEW_UNRESTRICTED` | off | `1` → run agent with `--dangerously-skip-permissions` |
| `AI_REVIEW_DRY_RUN` | off | `1` → print the review instead of posting |

## Security note

By default the agent runs with a **read-only tool allowlist**
(`Read`, `Grep`, `Glob`, and read-only `git` commands). It can explore the
whole repo but cannot write files, run arbitrary shell commands, or reach the
network. That matters because the agent processes untrusted PR content — a
malicious diff could otherwise try to prompt-inject the agent into leaking
your `ANTHROPIC_API_KEY` or tampering with the pipeline.

Set `AI_REVIEW_UNRESTRICTED=1` only for repos where every author is trusted
(it lets the agent run tests/linters itself, which can improve reviews).

## Try it locally

```sh
docker build -t ai-review .
docker run --rm \
  -e ANTHROPIC_API_KEY=sk-... \
  -e GITLAB_CI=1 -e CI_API_V4_URL=... -e CI_PROJECT_ID=... \
  -e CI_MERGE_REQUEST_IID=... -e GITLAB_TOKEN=... \
  -e AI_REVIEW_DRY_RUN=1 \
  -v /path/to/repo-checkout:/repo -w /repo \
  ai-review
```
