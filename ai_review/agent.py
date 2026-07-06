"""Run the Claude Code agent headlessly over the repo and parse its review."""

import json
import re
import subprocess

from .config import Config

# Read-only tool set: the agent can explore the whole repo and its git
# history, but cannot write files, run arbitrary commands, or reach the
# network. This matters because the agent reads untrusted PR code.
READ_ONLY_TOOLS = (
    "Read,Grep,Glob,"
    "Bash(git diff:*),Bash(git log:*),Bash(git show:*),Bash(git blame:*)"
)

REVIEW_INSTRUCTIONS = """\
You are an automated code reviewer running in CI. Review the changes of this
merge request. You have full read access to the repository checkout — use it:
read the surrounding code, related modules, and git history so you understand
the change in context instead of judging the diff in isolation.

Changed files:
{changed_files}

The diff (base {base_sha} -> HEAD {head_sha}):

```diff
{diff}
```

{skills}

{existing_feedback}

Review guidance:
- Focus on real problems: bugs, broken edge cases, security issues, race
  conditions, API misuse, violations of the skills above, and significant
  maintainability issues. Do not nitpick style that a linter would catch.
- Only comment on code changed in this diff (you may use unchanged code as
  context for a finding on a changed line).
- Report at most {max_findings} findings, most important first.
- Line numbers must refer to the NEW file version (the right side of the diff).

When you are done, your FINAL message must be ONLY a JSON object (no prose,
no markdown fence) with this exact shape:

{{
  "summary": "2-6 sentence overall review summary in markdown",
  "verdict": "approve" | "comment" | "request_changes",
  "findings": [
    {{
      "path": "relative/file/path.py",
      "line": 42,
      "severity": "high" | "medium" | "low",
      "title": "short one-line title",
      "body": "explanation in markdown, with a concrete suggestion"
    }}
  ]
}}
"""

VERIFY_INSTRUCTIONS = """\
You are fact-checking findings produced by an automated code review of this
repository. For each finding below, read the actual code (and as much
surrounding context as you need) and decide whether the finding is REAL and
worth telling a human about, or a false positive / already handled /
speculative.

Be adversarial: your job is to refute findings. Reject a finding if the
claimed problem cannot actually occur, is handled elsewhere, misreads the
code, or is pure speculation without evidence in the code.

Findings to verify:

{findings_json}

Your FINAL message must be ONLY a JSON object (no prose, no markdown fence):

{{
  "verdicts": [
    {{"index": 0, "valid": true, "reason": "one sentence"}},
    {{"index": 1, "valid": false, "reason": "one sentence"}}
  ]
}}

Include a verdict for every finding index.
"""


class ReviewResult:
    def __init__(self, summary: str, verdict: str, findings: list[dict]):
        self.summary = summary
        self.verdict = verdict
        self.findings = findings


def build_prompt(cfg: Config, base_sha: str, head: str, files: list[str],
                 diff: str, skills_block: str,
                 feedback_block: str = "") -> str:
    return REVIEW_INSTRUCTIONS.format(
        changed_files="\n".join(f"- {f}" for f in files) or "(none)",
        base_sha=base_sha[:12],
        head_sha=head[:12],
        diff=diff,
        skills=skills_block,
        existing_feedback=feedback_block,
        max_findings=cfg.max_findings,
    )


MARKER_COMMENT_RE = re.compile(r"<!--.*?-->\s*", re.DOTALL)


def render_existing_feedback(feedback: list[dict], max_items: int = 80,
                             max_body_chars: int = 1200,
                             max_total_chars: int = 30_000) -> str:
    """Render already-posted MR/PR comments for the prompt, with a
    do-not-repeat instruction. Returns "" when there is nothing."""
    items = []
    for f in feedback:
        body = MARKER_COMMENT_RE.sub("", f["body"]).strip()
        if not body:
            continue
        if len(body) > max_body_chars:
            body = body[:max_body_chars] + " [...]"
        where = ""
        if f.get("path"):
            where = f' path="{f["path"]}"'
            if f.get("line"):
                where += f' line="{f["line"]}"'
        resolved = ' resolved="true"' if f.get("resolved") else ""
        items.append(f'<comment author="{f["author"]}"{where}{resolved}>\n'
                     f"{body}\n</comment>")
    if not items:
        return ""
    # keep the most recent ones when over budget
    items = items[-max_items:]
    while items and sum(len(i) for i in items) > max_total_chars:
        items.pop(0)

    return (
        "# Feedback already posted on this merge request\n"
        "The comments below (from humans and previous automated reviews) are "
        "already on the MR. Do NOT repeat them: skip any finding that "
        "substantially makes the same point, even if you would word it "
        "differently or attach it to a nearby line. Comments marked "
        "resolved=\"true\" were addressed — only re-raise one if the current "
        "code clearly still has the problem. Your job is to add NEW insight "
        "only.\n\n" + "\n\n".join(items)
    )


def run_agent(cfg: Config, prompt: str) -> ReviewResult:
    final_text = _run_claude(cfg, prompt, cfg.max_turns)
    return _parse_review(final_text)


def verify_findings(cfg: Config, findings: list[dict]) -> list[dict]:
    """Second adversarial pass: drop findings the verifier refutes.

    Fails open — if the verification call itself breaks, keep all findings.
    """
    if not findings:
        return findings
    numbered = [{"index": i, **f} for i, f in enumerate(findings)]
    prompt = VERIFY_INSTRUCTIONS.format(
        findings_json=json.dumps(numbered, indent=2)
    )
    try:
        text = _run_claude(cfg, prompt, max_turns=min(cfg.max_turns, 30))
        verdicts = _extract_json(text).get("verdicts", [])
    except Exception as exc:  # noqa: BLE001 - verification must not kill the review
        print(f"[ai-review] verification pass failed ({exc}); keeping all findings")
        return findings

    rejected = {int(v["index"]) for v in verdicts
                if isinstance(v, dict) and not v.get("valid", True)}
    kept = [f for i, f in enumerate(findings) if i not in rejected]
    for v in verdicts:
        if isinstance(v, dict) and not v.get("valid", True):
            i = int(v["index"])
            if 0 <= i < len(findings):
                print(f"[ai-review] dropped finding "
                      f"'{findings[i]['title']}' — {v.get('reason', '')}")
    return kept


def _run_claude(cfg: Config, prompt: str, max_turns: int) -> str:
    cmd = ["claude", "-p", "--output-format", "json",
           "--max-turns", str(max_turns)]
    if cfg.model:
        cmd += ["--model", cfg.model]
    if cfg.unrestricted:
        cmd += ["--dangerously-skip-permissions"]
    else:
        cmd += ["--allowedTools", READ_ONLY_TOOLS]

    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        cwd=cfg.repo_dir,
        timeout=1800,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude exited with {proc.returncode}:\n{proc.stderr}\n{proc.stdout}"
        )

    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(f"claude reported an error: {envelope}")
    cost = envelope.get("total_cost_usd")
    if cost is not None:
        print(f"[ai-review] agent cost: ${cost:.4f}, "
              f"turns: {envelope.get('num_turns')}")
    return envelope.get("result", "")


def _parse_review(text: str) -> ReviewResult:
    data = _extract_json(text)
    findings = []
    for f in data.get("findings", []):
        try:
            findings.append({
                "path": str(f["path"]),
                "line": int(f.get("line") or 0),
                "severity": str(f.get("severity", "medium")).lower(),
                "title": str(f.get("title", "")).strip(),
                "body": str(f.get("body", "")).strip(),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return ReviewResult(
        summary=str(data.get("summary", "")).strip(),
        verdict=str(data.get("verdict", "comment")),
        findings=findings,
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    # tolerate a ```json fence or stray prose around the object
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise RuntimeError(
            f"could not parse review JSON from agent output:\n{text[:2000]}"
        )
