"""Client for the Kunpeng upstream-dashboard software list (scenario four).

The dashboard publishes the software catalogue the scenario-four workflow
mirrors into functional test scripts.  The API is public:

    GET {base}/api/v1/software?domain=kunpeng&page=N&page_size=100

and returns ``{"items": [...]}`` where each item carries at least ``name``,
``repo_url``, ``latest_version`` and ``is_active``.  A failed fetch returns
``None`` so the caller can skip the round entirely: one quiet day is cheaper
than guessing at a partial catalogue.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests

DASHBOARD_BASE = os.environ.get(
    "TESTGEN_DASHBOARD_BASE",
    "https://upstream-dashboard.test.osinfra.cn",
).rstrip("/")
_PAGE_SIZE = 100
_MAX_PAGES = 50
_REQUEST_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class DashboardSoftware:
    """One catalogue entry from the upstream dashboard."""

    name: str
    repo_url: str
    latest_version: str
    is_active: bool


def _parse_item(item: dict) -> DashboardSoftware | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    return DashboardSoftware(
        name=name,
        repo_url=str(item.get("repo_url") or "").strip(),
        latest_version=str(item.get("latest_version") or "").strip(),
        is_active=bool(item.get("is_active", True)),
    )


def fetch_dashboard_software(
    domain: str = "kunpeng",
    *,
    timeout: int = _REQUEST_TIMEOUT_SECONDS,
) -> list[DashboardSoftware] | None:
    """Return the full dashboard catalogue, or None when unreachable.

    Pages through the API until an empty ``items`` list.  Any request error
    is retried once; a second failure gives up for this round.
    """
    software: list[DashboardSoftware] = []
    for page in range(1, _MAX_PAGES + 1):
        url = f"{DASHBOARD_BASE}/api/v1/software"
        params = {"domain": domain, "page": page, "page_size": _PAGE_SIZE}
        last_error: Exception | None = None
        for attempt in (1, 2):
            try:
                response = requests.get(url, params=params, timeout=timeout)
                response.raise_for_status()
                payload = response.json()
                break
            except (requests.RequestException, ValueError) as error:
                last_error = error
        else:
            raise RuntimeError(
                f"dashboard request failed on page {page}: {last_error}"
            ) from last_error

        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            # A malformed page means the API contract changed; better to
            # skip the whole round than to generate from a partial list.
            return None
        if not items:
            break
        for item in items:
            if isinstance(item, dict):
                parsed = _parse_item(item)
                if parsed is not None:
                    software.append(parsed)
    return software
