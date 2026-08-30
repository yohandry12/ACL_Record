"""
Lumina Filters - Chaîne de filtres temps réel appliqués frame par frame.

Un FrameFilter transforme une frame BGR (numpy) pendant la capture.
FilterChain applique les filtres actifs en série avec un garde-fou :
un filtre trop lent (budget dépassé sur N frames consécutives) ou qui
lève une exception est désactivé à chaud — l'enregistrement continue.
"""

import time
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

import numpy as np


class FrameFilter(ABC):
    """Filtre appliqué à chaque frame pendant l'enregistrement."""

    name: str = "filter"

    def __init__(self):
        self.enabled = True

    @abstractmethod
    def process(self, frame: np.ndarray) -> np.ndarray:
        """Retourne la frame transformée (mêmes dimensions)."""
        ...


class FilterChain:
    """Applique une liste de FrameFilter avec garde-fou performance."""

    def __init__(self, filters: List[FrameFilter], frame_budget: float,
                 on_disable: Optional[Callable[[str], None]] = None,
                 max_slow_frames: int = 30):
        self.filters = filters
        self.frame_budget = frame_budget
        self.on_disable = on_disable
        self.max_slow_frames = max_slow_frames
        self._slow_counts = {id(f): 0 for f in filters}

    @property
    def active_count(self) -> int:
        return sum(1 for f in self.filters if f.enabled)

    def _disable(self, flt: FrameFilter):
        flt.enabled = False
        if self.on_disable:
            self.on_disable(flt.name)

    def process(self, frame: np.ndarray) -> np.ndarray:
        for flt in self.filters:
            if not flt.enabled:
                continue
            start = time.perf_counter()
            try:
                frame = flt.process(frame)
            except Exception:
                self._disable(flt)
                continue
            elapsed = time.perf_counter() - start
            if elapsed > self.frame_budget:
                self._slow_counts[id(flt)] += 1
                if self._slow_counts[id(flt)] >= self.max_slow_frames:
                    self._disable(flt)
            else:
                self._slow_counts[id(flt)] = 0
        return frame
