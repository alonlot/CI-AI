"""Provider auto-detection: figure out which CI platform we're running on."""

import os

from .base import Provider
from .github import GitHubProvider
from .gitlab import GitLabProvider


def detect_provider() -> Provider:
    if os.environ.get("GITLAB_CI"):
        return GitLabProvider()
    if os.environ.get("GITHUB_ACTIONS"):
        return GitHubProvider()
    raise RuntimeError(
        "Could not detect CI platform (expected GITLAB_CI or GITHUB_ACTIONS "
        "in the environment)."
    )
