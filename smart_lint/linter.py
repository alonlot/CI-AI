"""The lint itself: Claude API calls over the diff, no repo agent.

Each skill file is a rule set. The model checks the diff against every rule
and returns violations as guaranteed-valid JSON (structured outputs), so
there's nothing fuzzy to parse. Large diffs are linted in per-file batches
by the caller — this module lints one batch per call.
"""

import json

import anthropic

from .config import Config

SYSTEM_PROMPT = """\
You are a strict but fair lint engine. You receive a set of rule files
("skills") and a unified diff. Report every place the ADDED code (lines
starting with '+') violates one of the rules.

- Judge only the added/changed lines; unchanged context lines are for
  understanding only.
- Only report violations of the given rules — you are not a general code
  reviewer here. No violation without a rule that backs it.
- Do not report a violation you are unsure about; a lint must not cry wolf.
- `line` is the line number in the NEW version of the file (derive it from
  the @@ hunk headers).
- `rule` quotes or closely paraphrases the specific rule that was broken.

Suppressions: when the offending line — or the line directly above it —
contains a comment with `lint-ok: <reason>`, the developer has intentionally
suppressed the rule there. Put such cases in `suppressed` (including the
developer's reason) instead of `violations`. A bare `lint-ok` without a
reason does NOT suppress; report it as a normal violation.
"""

_VIOLATION_PROPS = {
    "skill": {"type": "string",
              "description": "name of the skill file the rule came from"},
    "path": {"type": "string"},
    "line": {"type": "integer"},
    "rule": {"type": "string"},
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "violations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    **_VIOLATION_PROPS,
                    "detail": {"type": "string",
                               "description": "what exactly violates the rule, one or two sentences"},
                },
                "required": ["skill", "path", "line", "rule", "detail"],
                "additionalProperties": False,
            },
        },
        "suppressed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    **_VIOLATION_PROPS,
                    "reason": {"type": "string",
                               "description": "the developer's lint-ok reason"},
                },
                "required": ["skill", "path", "line", "rule", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["violations", "suppressed"],
    "additionalProperties": False,
}


class BatchResult:
    def __init__(self, violations: list[dict], suppressed: list[dict],
                 input_tokens: int, output_tokens: int):
        self.violations = violations
        self.suppressed = suppressed
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def render_rules(skills: list[tuple[str, str]]) -> str:
    return "\n\n".join(
        f'<skill name="{name}">\n{content}\n</skill>' for name, content in skills
    )


def lint_batch(cfg: Config, rules_block: str, diff: str,
               client: anthropic.Anthropic) -> BatchResult:
    user = (f"# Rule skills\n\n{rules_block}\n\n"
            f"# Diff to lint\n\n```diff\n{diff}\n```")

    response = client.messages.create(
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("model refused the lint request")
    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            "lint output was truncated — raise SMART_LINT_MAX_TOKENS")

    text = next(b.text for b in response.content if b.type == "text")
    data = json.loads(text)
    return BatchResult(
        violations=data.get("violations", []),
        suppressed=data.get("suppressed", []),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
