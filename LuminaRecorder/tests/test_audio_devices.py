"""Tests du choix de périphérique micro (liste + sélection)."""

import time
from datetime import datetime, timedelta

import pytest

from core import recorder_core
from core.recorder_core import RecorderCore, list_input_devices, AudioDevice


class FakePyAudio:
    """Simule PyAudio avec 2 entrées, 1 sortie, et un défaut système."""

    DEVICES = [
        {'name': 'Micro Realtek', 'maxInputChannels': 2,
         'defaultSampleRate': 44100.0},
        {'name': 'Haut-parleurs', 'maxInputChannels': 0,
         'defaultSampleRate': 48000.0},
        {'name': 'AirPods Pro', 'maxInputChannels': 1,
         'defaultSampleRate': 8000.0},
    ]

    def __init__(self):
        self.terminated = False
        self.opened_kwargs = None

    def get_device_count(self):
        return len(self.DEVICES)

    def get_device_info_by_index(self, i):
        info = dict(self.DEVICES[i])
        info['index'] = i
        return info

    def get_default_input_device_info(self):
        return self.get_device_info_by_index(0)

    def terminate(self):
        self.terminated = True


def test_list_input_devices_keeps_only_inputs(monkeypatch):
    monkeypatch.setattr(recorder_core.pyaudio, 'PyAudio', FakePyAudio)
    devices = list_input_devices()
    assert [d.name for d in devices] == ['Micro Realtek', 'AirPods Pro']
    assert [d.index for d in devices] == [0, 2]
    assert devices[0].is_default is True
    assert devices[1].is_default is False
    assert devices[1].max_channels == 1


def test_list_input_devices_survives_pyaudio_failure(monkeypatch):
    """Un PyAudio cassé ne doit pas empêcher l'application de démarrer."""
    def boom():
        raise OSError("pas de service audio")

    monkeypatch.setattr(recorder_core.pyaudio, 'PyAudio', boom)
    assert list_input_devices() == []


def test_list_input_devices_terminates_pyaudio(monkeypatch):
    created = []

    def factory():
        fake = FakePyAudio()
        created.append(fake)
        return fake

    monkeypatch.setattr(recorder_core.pyaudio, 'PyAudio', factory)
    list_input_devices()
    assert created[0].terminated is True


def test_device_names_are_decoded(monkeypatch):
    """Les noms PortAudio arrivent en UTF-8 lu comme du latin-1."""
    class MojibakePyAudio(FakePyAudio):
        DEVICES = [{'name': 'RÃ©seau de microphones (Realtek Audio)',
                    'maxInputChannels': 2, 'defaultSampleRate': 44100.0}]

    monkeypatch.setattr(recorder_core.pyaudio, 'PyAudio', MojibakePyAudio)
    assert list_input_devices()[0].name == \
        'Réseau de microphones (Realtek Audio)'


def test_recorder_stores_audio_device_index():
    rec = RecorderCore(audio_enabled=True, audio_device_index=3)
    assert rec.audio_device_index == 3


def test_recorder_defaults_to_system_device():
    rec = RecorderCore()
    assert rec.audio_device_index is None


def test_video_waits_for_first_audio_chunk(monkeypatch):
    """L'ouverture de PortAudio prend ~1 s : la vidéo ne doit pas partir
    avant, sinon -shortest tronque cette seconde à l'encodage."""
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=True)
    order = []

    def fake_audio():
        order.append('audio_start')
        time.sleep(0.3)          # simule l'init lente de PortAudio
        rec._audio_ready.set()

    def fake_screen():
        order.append('video_start')

    monkeypatch.setattr(rec, '_capture_audio', fake_audio)
    monkeypatch.setattr(rec, '_capture_screen', fake_screen)

    rec.start_recording("ignore.mp4")
    rec.recording_thread.join(timeout=2.0)
    rec.audio_thread.join(timeout=2.0)

    assert order == ['audio_start', 'video_start']


def test_video_starts_even_if_audio_never_ready(monkeypatch):
    """Un micro qui n'ouvre jamais ne doit pas bloquer l'enregistrement."""
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=True)
    started = []

    monkeypatch.setattr(rec, '_capture_audio', lambda: rec._audio_ready.set())
    monkeypatch.setattr(rec, '_capture_screen', lambda: started.append(True))

    rec.start_recording("ignore.mp4")
    rec.recording_thread.join(timeout=2.0)
    assert started == [True]


def test_audio_disabled_produces_no_audio_thread(tmp_path):
    """audio_enabled=False : aucun thread audio, aucun WAV."""
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    _, audio_path = rec.stop_recording()
    assert rec.audio_thread is None
    assert audio_path == ""


def test_actual_fps_measured_at_stop(tmp_path):
    """Sur une machine lente la capture produit moins de frames que
    demandé : encoder au fps nominal accélérerait l'image."""
    import numpy as np

    rec = RecorderCore(resolution="160x120", fps=30, audio_enabled=False)
    rec._temp_dir = str(tmp_path)
    rec.is_recording = True
    rec.start_time = datetime.now() - timedelta(seconds=10)
    for _ in range(150):                      # 150 frames en 10 s = 15 fps
        rec._write_frame(np.zeros((120, 160, 3), dtype=np.uint8))
    rec.stop_recording()

    assert 14.0 < rec.actual_fps < 16.0       # et non 30


def test_actual_fps_defaults_to_nominal():
    rec = RecorderCore(fps=25, audio_enabled=False)
    assert rec.actual_fps == 25.0
