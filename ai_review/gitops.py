"""Git helpers: make sure the target branch is available and compute the diff."""

import subprocess


def _git(args: list[str], cwd: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout


def ensure_target_branch(repo_dir: str, target_branch: str) -> str:
    """Fetch the target branch and return the merge-base ref to diff against.

    CI runners often do shallow clones, so unshallow enough history for the
    merge-base to exist.
    """
    try:
        _git(["fetch", "--quiet", "origin", target_branch], cwd=repo_dir)
    except subprocess.CalledProcessError:
        pass  # branch ref may already be present locally

    is_shallow = _git(["rev-parse", "--is-shallow-repository"], cwd=repo_dir).strip()
    if is_shallow == "true":
        try:
            _git(["fetch", "--quiet", "--unshallow", "origin"], cwd=repo_dir)
        except subprocess.CalledProcessError:
            _git(["fetch", "--quiet", "--deepen=500", "origin"], cwd=repo_dir)

    return f"origin/{target_branch}"


def merge_base(repo_dir: str, target_ref: str) -> str:
    return _git(["merge-base", target_ref, "HEAD"], cwd=repo_dir).strip()


def head_sha(repo_dir: str) -> str:
    return _git(["rev-parse", "HEAD"], cwd=repo_dir).strip()


def changed_files(repo_dir: str, base_sha: str) -> list[str]:
    out = _git(["diff", "--name-only", f"{base_sha}..HEAD"], cwd=repo_dir)
    return [line for line in out.splitlines() if line.strip()]


def diff_text(repo_dir: str, base_sha: str, files: list[str] | None = None,
              max_chars: int = 300_000) -> str:
    args = ["diff", "--unified=5", f"{base_sha}..HEAD"]
    if files:
        args += ["--", *files]
    out = _git(args, cwd=repo_dir)
    if len(out) > max_chars:
        out = out[:max_chars] + "\n\n[... diff truncated for length ...]"
    return out
