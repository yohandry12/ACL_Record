import time
import numpy as np
import pytest

from filters.base import FrameFilter, FilterChain


class IdentityFilter(FrameFilter):
    name = "identity"

    def process(self, frame):
        return frame


class InvertFilter(FrameFilter):
    name = "invert"

    def process(self, frame):
        return 255 - frame


class SlowFilter(FrameFilter):
    name = "slow"

    def __init__(self, delay=0.001):
        super().__init__()
        self.delay = delay

    def process(self, frame):
        # Court : les tests utilisent un budget nul ou une horloge simulée
        # plutôt que d'attendre réellement
        time.sleep(self.delay)
        return frame


class CrashFilter(FrameFilter):
    name = "crash"

    def process(self, frame):
        raise RuntimeError("boom")


def make_frame():
    return np.zeros((10, 10, 3), dtype=np.uint8)


def test_chain_applies_filters_in_order():
    chain = FilterChain([InvertFilter()], frame_budget=1.0)
    out = chain.process(make_frame())
    assert out.max() == 255  # frame noire inversée -> blanche


def test_disabled_filter_is_skipped():
    f = InvertFilter()
    f.enabled = False
    chain = FilterChain([f], frame_budget=1.0)
    out = chain.process(make_frame())
    assert out.max() == 0  # rien appliqué


def test_slow_filter_disabled_after_30_consecutive_slow_frames():
    disabled = []
    f = SlowFilter(delay=0.02)
    # Budget nul : toute frame dépasse, quel que soit l'état de la machine
    chain = FilterChain([f], frame_budget=0.0,
                        on_disable=disabled.append, max_slow_frames=30)
    frame = make_frame()
    for _ in range(30):
        chain.process(frame)
    assert f.enabled is False
    assert disabled == ["slow"]
    assert chain.active_count == 0


def test_fast_frame_resets_slow_counter(monkeypatch):
    """Horloge simulée : mesurer le temps réel rendrait ce test instable
    (une frame « rapide » peut dépasser le budget si la machine est
    chargée, et le filtre serait désactivé à tort)."""
    from filters import base as filters_base

    horloge = {'t': 0.0}
    monkeypatch.setattr(filters_base.time, 'perf_counter',
                        lambda: horloge['t'])

    class FiltreControle(FrameFilter):
        name = "controle"

        def __init__(self):
            super().__init__()
            self.cout = 0.02          # dépasse le budget

        def process(self, frame):
            horloge['t'] += self.cout
            return frame

    f = FiltreControle()
    chain = FilterChain([f], frame_budget=0.001, max_slow_frames=30)
    frame = make_frame()

    for _ in range(29):               # 29 frames lentes : pas encore 30
        chain.process(frame)
    assert f.enabled is True

    f.cout = 0.0                      # une frame rapide remet le compteur à 0
    chain.process(frame)

    f.cout = 0.02
    for _ in range(29):               # 29 de plus : toujours pas 30 d'affilée
        chain.process(frame)
    assert f.enabled is True

    chain.process(frame)              # la 30e consécutive déclenche
    assert f.enabled is False


def test_crashing_filter_disabled_immediately_frame_preserved():
    disabled = []
    chain = FilterChain([CrashFilter(), InvertFilter()],
                        frame_budget=1.0, on_disable=disabled.append)
    out = chain.process(make_frame())
    assert disabled == ["crash"]
    assert out.max() == 255  # le filtre suivant a quand même tourné
