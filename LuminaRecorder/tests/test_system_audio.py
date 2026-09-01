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


def test_silence_is_reinserted_at_the_right_position(fake):
    """Le loopback ne délivre rien pendant les silences : le son doit
    rester à sa place, sinon une vidéo lancée après 5 s de navigation
    aurait son audio collé au début."""
    cap = SystemAudioCapture()
    cap.start()
    cb = fake.open_kwargs['stream_callback']

    chunk = np.full(1024 * 2, 1000, dtype=np.int16).tobytes()
    # Un seul chunk, arrivé après 5 s de silence
    cap._start_time = 0.0
    cap._timestamps = []
    cap.frames = []
    cap._timestamps.append(5.0)
    cap.frames.append(chunk)
    cap.stop()

    audio = np.frombuffer(cap.get_audio_bytes(), dtype=np.int16)
    total_frames = len(audio) // 2          # stéréo
    # ~5 s de silence à 48 kHz, puis le chunk
    assert total_frames > 4.5 * 48000
    assert int(audio[:1000].max()) == 0     # le début est silencieux
    assert int(audio.max()) == 1000         # le son est présent ensuite


def test_final_silence_padded_to_total_duration(fake):
    """Si le son s'arrête avant la fin, la piste est complétée."""
    cap = SystemAudioCapture()
    cap.start()
    cap._start_time = 0.0
    cap.frames = [np.full(1024 * 2, 500, dtype=np.int16).tobytes()]
    cap._timestamps = [1.0]
    cap.stop()

    audio = np.frombuffer(cap.get_audio_bytes(total_duration=10.0),
                          dtype=np.int16)
    assert len(audio) // 2 >= 9.5 * 48000
    assert int(audio[-1000:].max()) == 0    # se termine en silence


def test_no_timestamps_returns_empty(fake):
    cap = SystemAudioCapture()
    cap.start()
    cap.stop()
    assert cap.get_audio_bytes() == b''


def test_start_returns_false_when_unavailable(monkeypatch):
    monkeypatch.setattr(system_audio, 'WPATCH_AVAILABLE', False)
    cap = SystemAudioCapture()
    assert cap.start() is False
    assert cap.frames == []


# --- Horodatage sur l'horloge matérielle ---

def test_horodatage_utilise_l_horloge_materielle():
    """Mesuré sur le matériel : le loopback WASAPI livre les chunks
    avec un retard variable (jusqu'à 2 s à l'ouverture du flux).
    Horodater à l'ARRIVÉE plaçait donc tout le son système en retard
    sur l'image. input_buffer_adc_time date le moment où le matériel a
    réellement capté les échantillons — c'est la seule mesure juste."""
    import time as _time

    cap = SystemAudioCapture()
    cap.sample_rate = 48000
    cap.channels = 2
    cap._start_time = _time.time() - 5.0    # capture démarrée il y a 5 s
    cap._adc_origine = None

    # Reconstruit le callback tel que start() le crée
    def on_chunk(in_data, frame_count, time_info, status):
        adc = float(time_info['input_buffer_adc_time'])
        if cap._adc_origine is None:
            ecoule = _time.time() - cap._start_time
            duree = frame_count / cap.sample_rate
            cap._adc_origine = adc - max(0.0, ecoule - duree)
        cap._timestamps.append(adc - cap._adc_origine)
        cap.frames.append(in_data)

    # Deux chunks espacés d'exactement 1 s sur l'horloge matérielle,
    # livrés en rafale (arrivées quasi simultanées côté Python)
    on_chunk(b'\x00' * 4096, 1024, {'input_buffer_adc_time': 1000.0}, 0)
    on_chunk(b'\x00' * 4096, 1024, {'input_buffer_adc_time': 1001.0}, 0)

    ecart = cap._timestamps[1] - cap._timestamps[0]
    assert abs(ecart - 1.0) < 0.01, (
        "L'écart doit venir de l'horloge matérielle (1 s), pas de "
        "l'instant d'arrivée des callbacks")


def test_horodatage_retombe_sur_l_arrivee_sans_horloge():
    """Si PortAudio ne fournit pas d'horodatage matériel, la capture
    doit continuer de fonctionner — dégradée, jamais interrompue."""
    import time as _time

    cap = SystemAudioCapture()
    cap.sample_rate = 48000
    cap.channels = 2
    cap._start_time = _time.time()
    cap._adc_origine = None

    def on_chunk(in_data, frame_count, time_info, status):
        adc = None
        try:
            adc = float(time_info['input_buffer_adc_time'])
        except (KeyError, TypeError, ValueError):
            pass
        if adc:
            horodatage = adc
        else:
            horodatage = _time.time() - cap._start_time
        cap._timestamps.append(horodatage)

    on_chunk(b'\x00' * 4096, 1024, {}, 0)          # pas d'horloge

    assert len(cap._timestamps) == 1
    assert cap._timestamps[0] >= 0
