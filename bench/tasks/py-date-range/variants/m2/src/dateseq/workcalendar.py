"""Working days: weekdays that are not public holidays, with holidays from the HR service.

The HR service needs an API token in the ``HR_API_TOKEN`` environment variable. The CI
runner has it; developer machines usually do not.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Iterable, Mapping
from datetime import date

HR_URL = "https://hr.office.internal/api/v1/holidays"
TOKEN_VARIABLE = "HR_API_TOKEN"


def parse_holidays(text: str) -> dict[date, str]:
    """The holidays in an HR service reply: ``{"holidays": [{"date": ..., "name": ...}]}``."""
    document = json.loads(text)
    return {date.fromisoformat(item["date"]): item["name"] for item in document["holidays"]}


def working_days(dates: Iterable[date], holidays: Mapping[date, str]) -> list[date]:
    """The dates that are Monday to Friday and not holidays, in their order."""
    return [day for day in dates if day.weekday() < 5 and day not in holidays]


def fetch_holidays(year: int, country: str = "PT", timeout_s: float = 5.0) -> dict[date, str]:
    """Ask the HR service for the public holidays of one year in one country."""
    token = os.environ[TOKEN_VARIABLE]
    request = urllib.request.Request(
        f"{HR_URL}/{country}/{year}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return parse_holidays(response.read().decode("utf-8"))
