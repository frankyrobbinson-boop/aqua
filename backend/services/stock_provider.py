"""Provider-agnostic stock-footage interface.

Concrete providers (Pexels, Storyblocks, Pond5, …) implement StockProvider.
The visual_service consumes the interface, not the concrete classes — swap
providers by changing one constructor.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class StockClip:
    """One candidate stock-footage clip returned by a provider's search."""
    id: str
    download_url: str
    duration: float  # seconds
    width: int
    height: int
    provider: str
    preview_url: Optional[str] = None  # thumbnail / first-frame image URL
    page_url: Optional[str] = None     # provider page URL (slug often descriptive)


class StockProvider(ABC):
    @abstractmethod
    def search(
        self,
        query: str,
        min_duration: float,
        orientation: str = "landscape",
        max_results: int = 10,
    ) -> List[StockClip]:
        """Return candidate clips matching the query.

        Implementations should filter out clips shorter than min_duration where
        possible at the API level. Caller picks the best candidate.
        """

    @abstractmethod
    def download(self, clip: StockClip, output_path: str) -> str:
        """Download the clip to output_path. Returns the saved path."""


def pick_best(clips: List[StockClip], min_duration: float) -> Optional[StockClip]:
    """Default candidate-picking strategy: respect the provider's relevance
    ordering (Pexels returns most-relevant first). Pick the first qualifying-
    duration clip. Falls back to the longest clip if none meet duration."""
    qualifying = [c for c in clips if c.duration >= min_duration]
    if qualifying:
        return qualifying[0]
    if not clips:
        return None
    return max(clips, key=lambda c: c.duration)
