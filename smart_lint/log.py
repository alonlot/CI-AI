"""Job-log helpers: collapsible sections on GitLab, plain headers elsewhere."""

import os
import sys
import time


def _on_gitlab() -> bool:
    return bool(os.environ.get("GITLAB_CI"))


class Section:
    """Collapsible section in the GitLab job log (plain header elsewhere).

    Usage:
        with Section("skills", "Loaded skills"):
            print(...)
    """

    def __init__(self, slug: str, header: str, collapsed: bool = True):
        self.slug = slug
        self.header = header
        self.collapsed = collapsed

    def __enter__(self):
        if _on_gitlab():
            opts = "[collapsed=true]" if self.collapsed else ""
            sys.stdout.write(
                f"\x1b[0Ksection_start:{int(time.time())}:{self.slug}{opts}"
                f"\r\x1b[0K\x1b[1m{self.header}\x1b[0m\n")
        else:
            print(f"--- {self.header} ---")
        sys.stdout.flush()
        return self

    def __exit__(self, *exc):
        if _on_gitlab():
            sys.stdout.write(
                f"\x1b[0Ksection_end:{int(time.time())}:{self.slug}\r\x1b[0K\n")
        sys.stdout.flush()
        return False


def bold(text: str) -> str:
    return f"\x1b[1m{text}\x1b[0m"


def red(text: str) -> str:
    return f"\x1b[31;1m{text}\x1b[0m"


def green(text: str) -> str:
    return f"\x1b[32;1m{text}\x1b[0m"


def yellow(text: str) -> str:
    return f"\x1b[33m{text}\x1b[0m"
