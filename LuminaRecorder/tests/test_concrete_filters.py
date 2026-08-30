import numpy as np

from filters.privacy_blur_filter import PrivacyBlurFilter
from filters.clean_canvas_filter import CleanCanvasFilter
from filters.overlay_filter import OverlayFilter


def make_frame(h=200, w=300):
    # Bruit aléatoire : un flou gaussien y est mesurable (variance chute)
    rng = np.random.default_rng(42)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


def test_privacy_blur_blurs_registered_region():
    flt = PrivacyBlurFilter()
    flt.service.add_blur_region(50, 50, 100, 60, blur_type='gaussian',
                                strength=25, reason='test')
    frame = make_frame()
    out = flt.process(frame)
    region_before = frame[50:110, 50:150].astype(float)
    region_after = out[50:110, 50:150].astype(float)
    assert out.shape == frame.shape
    assert region_after.var() < region_before.var()  # flou = variance réduite


def test_privacy_blur_without_region_is_identity():
    flt = PrivacyBlurFilter()
    frame = make_frame()
    out = flt.process(frame)
    assert np.array_equal(out, frame)


def test_clean_canvas_returns_same_shape():
    flt = CleanCanvasFilter()
    frame = make_frame()
    out = flt.process(frame)
    assert out.shape == frame.shape
    assert out.dtype == frame.dtype


def test_overlay_draws_pixels():
    flt = OverlayFilter()
    frame = np.zeros((400, 600, 3), dtype=np.uint8)
    flt.process(frame)          # 1er appel : initialise les métriques
    out = flt.process(frame)
    assert out.shape == frame.shape
    assert out.sum() > 0        # du texte/fond a été dessiné sur du noir
