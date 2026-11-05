"""Cross-round state for scenario four (test-script generation).

Records per-app outcomes on the ``testgen-log`` branch of this repository so
successive scheduled rounds converge instead of re-generating the same app:

    testgen-log/{app}/done       — PR delivered (content: PR URL)
    testgen-log/{app}/exhausted  — retries used up (content: findings)

Storage reuses :mod:`scripts.lib.ci_data` (GitHub Contents API with sha-based
409 retry).  Human override is simply deleting the marker file.
"""

from __future__ import annotations

import re

from scripts.lib import ci_data

TESTGEN_BRANCH = "testgen-log"
_APP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _path(app: str, marker: str) -> str:
    if not _APP_NAME_RE.match(app):
        raise ValueError(f"invalid app name for state path: {app!r}")
    return f"testgen-log/{app}/{marker}"


def is_done(app: str) -> bool:
    return bool(ci_data.read_file(_path(app, "done"), branch=TESTGEN_BRANCH))


def mark_done(app: str, pr_url: str) -> None:
    ci_data.write_file(
        _path(app, "done"),
        pr_url,
        f"testgen: mark {app} done ({pr_url})",
        branch=TESTGEN_BRANCH,
    )


def done_pr_url(app: str) -> str:
    return ci_data.read_file(_path(app, "done"), branch=TESTGEN_BRANCH).strip()


def is_exhausted(app: str) -> bool:
    return bool(ci_data.read_file(_path(app, "exhausted"), branch=TESTGEN_BRANCH))


def mark_exhausted(app: str, reason: str) -> None:
    ci_data.write_file(
        _path(app, "exhausted"),
        reason,
        f"testgen: mark {app} exhausted",
        branch=TESTGEN_BRANCH,
    )
