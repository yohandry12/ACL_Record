"""Tests de la capture du son système (loopback WASAPI)."""

import numpy as np
import pytest

from core import system_audio
from core.system_audio import (SystemAudioCapture, system_audio_is_available,
                               find_loopback_device)


class FakeStream:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.closed = False

    def start_stream(self):
        self.started = True

    def stop_stream(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeWPatch:
    """Simule pyaudiowpatch avec un périphérique de sortie et son loopback."""
    paInt16 = 8
    paWASAPI = 13
    paContinue = 0
    paComplete = 1

    LOOPBACK = {'index': 13, 'name': 'Haut-parleurs (Realtek) [Loopback]',
                'defaultSampleRate': 48000.0, 'maxInputChannels': 2}

    def __init__(self):
        self.stream = FakeStream()
        self.open_kwargs = None
        self.terminated = False

    # --- API PyAudio utilisée par le module ---
    def PyAudio(self):
        return self

    def get_host_api_info_by_type(self, kind):
        return {'defaultOutputDevice': 5}

    def get_device_info_by_index(self, i):
        return {'index': 5, 'name': 'Haut-parleurs (Realtek)'}

    def get_loopback_device_info_generator(self):
        yield dict(self.LOOPBACK)

    def open(self, **kwargs):
        self.open_kwargs = kwargs
        return self.stream

    def terminate(self):
        self.terminated = True


@pytest.fixture
def fake(monkeypatch):
    f = FakeWPatch()
    monkeypatch.setattr(system_audio, 'pyaudiowpatch', f)
    monkeypatch.setattr(system_audio, 'WPATCH_AVAILABLE', True)
    return f


def test_unavailable_without_pyaudiowpatch(monkeypatch):
    monkeypatch.setattr(system_audio, 'WPATCH_AVAILABLE', False)
    assert system_audio_is_available() is False


def test_available_with_pyaudiowpatch(fake):
    assert system_audio_is_available() is True


def test_find_loopback_matches_default_output(fake):
    device = find_loopback_device()
    assert device is not None
    assert device['index'] == 13
    assert int(device['defaultSampleRate']) == 48000


def test_find_loopback_returns_none_without_wpatch(monkeypatch):
    monkeypatch.setattr(system_audio, 'WPATCH_AVAILABLE', False)
    assert find_loopback_device() is None


def test_capture_uses_loopback_device_and_its_rate(fake):
    cap = SystemAudioCapture()
    assert cap.start() is True
    assert fake.open_kwargs['input_device_index'] == 13
    assert fake.open_kwargs['rate'] == 48000
    assert fake.open_kwargs['channels'] == 2
    # Le loopback ne délivre rien dans le silence : le mode bloquant
    # gèlerait, seul le callback est utilisable
    assert fake.open_kwargs['stream_callback'] is not None
    assert fake.stream.started is True
    cap.stop()


def test_stop_releases_stream(fake):
    cap = SystemAudioCapture()
    cap.start()
    cap.stop()
    assert fake.stream.stopped is True
    assert fake.stream.closed is True
    assert fake.terminated is True


def test_collected_chunks_are_returned(fake):
    cap = SystemAudioCapture()
    cap.start()
    cb = fake.open_kwargs['stream_callback']
    chunk = np.zeros(1024 * 2, dtype=np.int16).tobytes()
    cb(chunk, 1024, None, 0)
    cb(chunk, 1024, None, 0)
    cap.stop()
    assert len(cap.frames) == 2


def test_gain_is_applied_to_system_audio(fake):
    cap = SystemAudioCapture(gain=0.5)
    cap.start()
    cb = fake.open_kwargs['stream_callback']
    loud = np.full(2048, 10000, dtype=np.int16).tobytes()
    cb(loud, 1024, None, 0)
    cap.stop()
    out = np.frombuffer(cap.frames[0], dtype=np.int16)
    assert int(out.max()) == 5000


def test_start_returns_false_when_unavailable(monkeypatch):
    monkeypatch.setattr(system_audio, 'WPATCH_AVAILABLE', False)
    cap = SystemAudioCapture()
    assert cap.start() is False
    assert cap.frames == []
