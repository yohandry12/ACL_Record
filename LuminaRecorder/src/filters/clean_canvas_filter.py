"""Adaptateur FrameFilter pour CleanCanvasEngine (masquage notifications)."""

import numpy as np

from ai.clean_canvas import CleanCanvasEngine
from .base import FrameFilter


class CleanCanvasFilter(FrameFilter):
    name = "clean_canvas"

    def __init__(self):
        super().__init__()
        self.engine = CleanCanvasEngine(auto_hide=True)

    def process(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        return self.engine.process_frame(frame, w, h)
