"""Adaptateur FrameFilter pour PrivacyBlurService (flou confidentialité)."""

import numpy as np

from services.privacy_blur import PrivacyBlurService
from .base import FrameFilter


class PrivacyBlurFilter(FrameFilter):
    name = "privacy_blur"

    def __init__(self):
        super().__init__()
        self.service = PrivacyBlurService()

    def process(self, frame: np.ndarray) -> np.ndarray:
        return self.service.process_frame(frame)
