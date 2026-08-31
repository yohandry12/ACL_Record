import threading

import numpy as np
import cv2
import pytest

from core.recorder_core import RecorderCore
from filters.base import FrameFilter
import core.recorder_core as recorder_core_module


class WhiteFilter(FrameFilter):
    name = "white"

    def process(self, frame):
        return np.full_like(frame, 255)


def make_frame(h=120, w=160):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_frames_written_to_disk_not_ram(tmp_path):
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)  # rediriger les fichiers temporaires
    for _ in range(20):
        rec._write_frame(make_frame())
    video_path, _ = rec.stop_recording()
    assert not hasattr(rec, 'frames') or rec.frames == []  # plus de buffer RAM
    cap = cv2.VideoCapture(video_path)
    assert cap.isOpened()
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 20
    cap.release()


def test_filters_applied_before_write(tmp_path):
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=False,
                       filters=[WhiteFilter()])
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    for _ in range(5):
        rec._write_frame(make_frame())
    video_path, _ = rec.stop_recording()
    cap = cv2.VideoCapture(video_path)
    ok, frame = cap.read()
    cap.release()
    assert ok
    assert frame.mean() > 200  # frames noires devenues blanches (MJPG avec perte)


def test_stop_without_frames_returns_empty(tmp_path):
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    video_path, audio_path = rec.stop_recording()
    assert video_path == ""
    assert audio_path == ""


class EcranSimule:
    """Écran de test : échoue les `echecs` premiers appels, puis rend une
    image. Compte les appels pour vérifier les tentatives réelles."""

    def __init__(self, echecs=0, erreur="écran perdu", h=120, w=160):
        self.echecs = echecs
        self.erreur = erreur
        self.appels = 0
        self._image = np.zeros((h, w, 4), dtype=np.uint8)
        self.ferme = False

    def grab(self, region):
        self.appels += 1
        if self.appels <= self.echecs:
            raise RuntimeError(self.erreur)
        return self._image

    def close(self):
        self.ferme = True


def _brancher_ecran(rec, ecran):
    rec._open_screen_capture = lambda: ecran


def test_capture_error_stops_recording_and_notifies(tmp_path):
    """Une panne durable finit par arrêter l'enregistrement et prévenir."""
    errors = []
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=False,
                       on_capture_error=errors.append)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    _brancher_ecran(rec, EcranSimule(echecs=10 ** 6))
    rec.MAX_ECHECS_CAPTURE = 3      # évite d'attendre 60 échecs en test

    rec._capture_screen()           # appel direct, synchrone

    assert rec.is_recording is False
    assert errors and "écran perdu" in errors[0]


def test_frame_ratee_n_interrompt_pas_l_enregistrement(tmp_path):
    """Constaté en usage réel : une seule erreur BitBlt tuait tout
    l'enregistrement. Ces échecs sont passagers (verrouillage de session,
    application en plein écran exclusif, écran en veille) — perdre
    quelques images vaut mieux que perdre la capture entière."""
    errors = []
    rec = RecorderCore(resolution="160x120", fps=60, audio_enabled=False,
                       on_capture_error=errors.append)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    ecran = EcranSimule(echecs=5)
    _brancher_ecran(rec, ecran)

    def arreter_apres_quelques_images():
        while rec._frame_count < 3:
            pass
        rec.is_recording = False

    t = threading.Thread(target=arreter_apres_quelques_images, daemon=True)
    t.start()
    rec._capture_screen()
    t.join(timeout=5)

    assert rec._frame_count >= 3        # a repris après les échecs
    assert errors == []                 # aucune alerte pour un incident passager


def test_session_de_capture_fermee_a_la_fin(tmp_path):
    """Le contexte GDI est libéré dans le thread qui l'a ouvert."""
    rec = RecorderCore(resolution="160x120", fps=60, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    ecran = EcranSimule()
    _brancher_ecran(rec, ecran)

    def arreter():
        while rec._frame_count < 2:
            pass
        rec.is_recording = False

    t = threading.Thread(target=arreter, daemon=True)
    t.start()
    rec._capture_screen()
    t.join(timeout=5)

    assert ecran.ferme is True


def test_start_recording_uses_fresh_audio_ready_event(tmp_path, monkeypatch):
    """C1 : deux enregistrements successifs ne doivent pas partager le
    même Event. Si le thread audio du run précédent est encore vivant à
    l'appel suivant, son `finally: set()` tardif ne doit pas débloquer
    prématurément le second run."""
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=True)
    rec._temp_dir = str(tmp_path)

    # Empêche le vrai thread audio de démarrer (pas de matériel requis) :
    # on veut seulement observer l'identité/état de l'Event.
    monkeypatch.setattr(rec, "_capture_audio", lambda: None)

    rec.start_recording(str(tmp_path / "out.mp4"))
    first_event = rec._audio_ready
    rec.is_recording = False
    if rec.recording_thread:
        rec.recording_thread.join(timeout=2.0)
    if rec.audio_thread:
        rec.audio_thread.join(timeout=2.0)

    # Simule le thread précédent encore vivant : il "set()" son ancien
    # Event après le second clear/remplacement.
    first_event.clear()

    rec.start_recording(str(tmp_path / "out2.mp4"))
    second_event = rec._audio_ready
    rec.is_recording = False
    if rec.recording_thread:
        rec.recording_thread.join(timeout=2.0)
    if rec.audio_thread:
        rec.audio_thread.join(timeout=2.0)

    assert second_event is not first_event
    assert not second_event.is_set()  # non déjà armé par le run précédent

    # L'ancien Event peut être signalé sans effet sur le nouveau
    first_event.set()
    assert not second_event.is_set()


class _FakeStream:
    """Faux stream PyAudio dont start_stream() lève (micro débranché)."""

    def __init__(self):
        self.stop_called = False
        self.close_called = False

    def start_stream(self):
        raise OSError("micro débranché")

    def is_active(self):
        return False

    def stop_stream(self):
        self.stop_called = True

    def close(self):
        self.close_called = True


class _FakePyAudio:
    instances = []

    def __init__(self):
        self.terminated = False
        self.stream = None
        _FakePyAudio.instances.append(self)

    def open(self, **kwargs):
        self.stream = _FakeStream()
        return self.stream

    def terminate(self):
        self.terminated = True


def test_capture_audio_closes_stream_before_terminate_on_error(monkeypatch):
    """C2 : si start_stream() lève, le stream doit être stop/close AVANT
    p.terminate() (comportement non défini sinon côté PortAudio)."""
    _FakePyAudio.instances = []
    monkeypatch.setattr(recorder_core_module.pyaudio, "PyAudio", _FakePyAudio)

    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=True)
    rec.is_recording = True

    rec._capture_audio()  # appel direct, synchrone

    assert len(_FakePyAudio.instances) == 1
    p = _FakePyAudio.instances[0]
    assert p.stream is not None
    assert p.stream.stop_called is True
    assert p.stream.close_called is True
    assert p.terminated is True
    assert rec._audio_ready.is_set()  # la vidéo ne doit jamais rester bloquée
