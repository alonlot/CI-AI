"""The lint itself: one Claude API call over the diff, no repo agent.

Each skill file is a rule set. The model checks the diff against every rule
and returns violations as guaranteed-valid JSON (structured outputs), so
there's nothing fuzzy to parse.
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
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "violations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string",
                              "description": "name of the skill file the rule came from"},
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "rule": {"type": "string"},
                    "detail": {"type": "string",
                               "description": "what exactly violates the rule, one or two sentences"},
                },
                "required": ["skill", "path", "line", "rule", "detail"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["violations"],
    "additionalProperties": False,
}


def lint(cfg: Config, skills: list[tuple[str, str]], diff: str) -> list[dict]:
    rules = "\n\n".join(
        f'<skill name="{name}">\n{content}\n</skill>' for name, content in skills
    )
    user = (f"# Rule skills\n\n{rules}\n\n"
            f"# Diff to lint\n\n```diff\n{diff}\n```")

    client = anthropic.Anthropic()
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
    return json.loads(text)["violations"]
