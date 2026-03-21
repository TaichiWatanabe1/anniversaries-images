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