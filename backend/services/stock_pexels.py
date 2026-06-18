"""Pexels Videos API implementation of StockProvider.

Env:
    PEXELS_API_KEY — get one free at https://www.pexels.com/api/

Notes:
    Free tier: 200 requests/hour, 20k/month. A 10-min video at ~30 scenes
    fits easily inside the hourly limit.
"""

import os
import shutil
import urllib.parse
from typing import List

import requests
from dotenv import load_dotenv

from services.stock_provider import StockClip, StockProvider

load_dotenv()

_SEARCH_URL = "https://api.pexels.com/videos/search"
_TARGET_W, _TARGET_H = 1920, 1080


class PexelsProvider(StockProvider):
    name = "pexels"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("PEXELS_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "PEXELS_API_KEY not set. Get one at https://www.pexels.com/api/ "
                "and add it to backend/.env"
            )
        self._headers = {"Authorization": self.api_key}

    def search(
        self,
        query: str,
        min_duration: float,
        orientation: str = "landscape",
        max_results: int = 10,
    ) -> List[StockClip]:
        params = {
            "query": query,
            "per_page": max_results,
            "orientation": orientation,
            "size": "medium",  # ≥ HD; "large" forces 4K+ and starves results
        }
        url = f"{_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        response = requests.get(url, headers=self._headers, timeout=20)
        response.raise_for_status()
        data = response.json()

        clips: List[StockClip] = []
        for video in data.get("videos", []):
            file = _pick_video_file(video.get("video_files", []))
            if not file:
                continue
            clips.append(StockClip(
                id=str(video["id"]),
                download_url=file["link"],
                duration=float(video.get("duration", 0)),
                width=int(file.get("width") or video.get("width") or 0),
                height=int(file.get("height") or video.get("height") or 0),
                provider=self.name,
                preview_url=video.get("image"),
                page_url=video.get("url"),
            ))
        return clips

    def download(self, clip: StockClip, output_path: str) -> str:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with requests.get(clip.download_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(output_path, "wb") as f:
                shutil.copyfileobj(r.raw, f)
        return output_path


def _pick_video_file(files: list) -> dict | None:
    """Pick the smallest MP4 that's at least 1920x1080. Prefer just-big-enough
    over 4K to keep download size and ffmpeg work down."""
    mp4s = [
        f for f in files
        if (f.get("file_type") == "video/mp4")
        and (f.get("width") or 0) >= _TARGET_W
        and (f.get("height") or 0) >= _TARGET_H
    ]
    if mp4s:
        return min(mp4s, key=lambda f: f.get("width", 0) * f.get("height", 0))
    # No HD+ available — fall back to the largest MP4 we can get.
    any_mp4 = [f for f in files if f.get("file_type") == "video/mp4"]
    if any_mp4:
        return max(any_mp4, key=lambda f: f.get("width", 0) * f.get("height", 0))
    return None
