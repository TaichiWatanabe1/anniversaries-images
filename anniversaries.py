from datetime import datetime
from zoneinfo import ZoneInfo
import requests


def get_today_mmdd(tz: str = "Asia/Tokyo") -> str:
    now = datetime.now(ZoneInfo(tz))
    return now.strftime("%m%d")


def get_today_date(tz: str = "Asia/Tokyo") -> str:
    now = datetime.now(ZoneInfo(tz))
    return now.strftime("%Y/%m/%d")


def fetch_anniversaries(mmdd: str) -> list[str]:
    url = f"https://api.whatistoday.cyou/v3/anniv/{mmdd}"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    anniversaries = [
        data.get("anniv1", ""),
        data.get("anniv2", ""),
        data.get("anniv3", ""),
        data.get("anniv4", ""),
        data.get("anniv5", ""),
    ]
    return [x for x in anniversaries if x]


def fetch_wikipedia_on_this_day_holidays(
    mmdd: str,
    *,
    language: str = "en",
    user_agent: str = "anniversaries-images/1.0 (contact: dev@example.com)",
) -> list[str]:
    """Fetch holiday topics from Wikipedia 'On this day' API."""
    if len(mmdd) != 4 or not mmdd.isdigit():
        raise ValueError("mmdd must be a 4-digit string like '0323'.")

    month = mmdd[:2]
    day = mmdd[2:]
    url = f"https://{language}.wikipedia.org/api/rest_v1/feed/onthisday/holidays/{month}/{day}"
    headers = {"User-Agent": user_agent}

    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    data = response.json()

    holidays = []
    for item in data.get("holidays", []):
        text = item.get("text", "")
        if text:
            holidays.append(text)
    return holidays
