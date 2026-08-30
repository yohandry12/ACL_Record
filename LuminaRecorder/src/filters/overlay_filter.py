"""Adaptateur FrameFilter pour SystemOverlayService (métriques CPU/RAM/FPS)."""

import numpy as np

from services.system_overlay import SystemOverlayService, OverlayConfig
from .base import FrameFilter


class OverlayFilter(FrameFilter):
    name = "overlay"

    def __init__(self):
        super().__init__()
        # update_interval bas pour que les métriques apparaissent vite
        self.service = SystemOverlayService(OverlayConfig(update_interval=0.5))

    def process(self, frame: np.ndarray) -> np.ndarray:
        return self.service.draw_overlay(frame)
