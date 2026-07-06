"""Skill loading.

A "skill" is just a markdown file with review guidance (team conventions,
security checklist, style rules...). Every ``*.md`` file found in the skill
directories is injected into the reviewer's prompt, so extending the review
is: drop a new .md file in a skills dir, done.

Search order (later files can build on earlier ones):
  1. built-in skills baked into the Docker image  (AI_REVIEW_BUILTIN_SKILLS_DIR)
  2. extra dirs given via AI_REVIEW_SKILLS_DIRS (comma separated)
  3. ``.ai-review/skills/`` inside the reviewed repo itself
"""

import os

from .config import Config


def load_skills(cfg: Config) -> list[tuple[str, str]]:
    """Return (name, content) pairs for every discovered skill file."""
    dirs: list[str] = []
    if cfg.builtin_skills_dir:
        dirs.append(cfg.builtin_skills_dir)
    dirs.extend(cfg.extra_skills_dirs)
    dirs.append(os.path.join(cfg.repo_dir, cfg.repo_skills_dir))

    skills: list[tuple[str, str]] = []
    seen_names: set[str] = set()
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.endswith(".md") or fname.startswith("_"):
                continue
            name = os.path.splitext(fname)[0]
            path = os.path.join(d, fname)
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read().strip()
            if not content:
                continue
            # a repo-local skill with the same name overrides a built-in one
            if name in seen_names:
                skills = [(n, c) for n, c in skills if n != name]
            seen_names.add(name)
            skills.append((name, content))
    return skills


def render_skills(skills: list[tuple[str, str]]) -> str:
    if not skills:
        return ""
    parts = ["# Team review skills\n"
             "Apply each of the following review guidelines. If a finding "
             "comes from one of these skills, mention the skill name in the "
             "finding body.\n"]
    for name, content in skills:
        parts.append(f"<skill name=\"{name}\">\n{content}\n</skill>")
    return "\n\n".join(parts)
