import threading
import time

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


def make_frame(h=120, w=160, value=0):
    return np.full((h, w, 3), value, dtype=np.uint8)


SOI = b'\xff\xd8\xff'   # début d'une image JPEG


def paquets(path):
    """Les images JPEG du flux brut, dans l'ordre.

    Le fichier brut est un MJPEG nu : une suite d'images JPEG à cadence
    constante. Compter les images, c'est compter les marqueurs SOI.
    """
    from pathlib import Path
    data = Path(path).read_bytes()
    return [SOI + p for p in data.split(SOI)[1:]]


def decoder(paquet):
    return cv2.imdecode(np.frombuffer(paquet, dtype=np.uint8), cv2.IMREAD_COLOR)


def test_frames_written_to_disk_not_ram(tmp_path):
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)  # rediriger les fichiers temporaires
    t0 = time.time()
    rec._t0 = t0
    for i in range(20):
        rec._write_frame(make_frame(), t=t0 + i / 10)
    rec._finalize_raw_video(t0 + 2.0)
    video_path, _ = rec.stop_recording()
    assert not hasattr(rec, 'frames') or rec.frames == []  # plus de buffer RAM
    assert len(paquets(video_path)) == 20


def test_filters_applied_before_write(tmp_path):
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=False,
                       filters=[WhiteFilter()])
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    t0 = time.time()
    rec._t0 = t0
    for i in range(5):
        rec._write_frame(make_frame(), t=t0 + i / 10)
    rec._finalize_raw_video(t0 + 0.5)
    video_path, _ = rec.stop_recording()
    frame = decoder(paquets(video_path)[0])
    assert frame is not None
    assert frame.mean() > 200  # frames noires devenues blanches (JPEG avec perte)


# --- Cadence constante par horodatage -----------------------------------
#
# Mesuré sur un enregistrement réel : la capture tournait à ~11 im/s sur
# une page statique puis ~20 im/s sur une vidéo, pour une moyenne de
# 17,47. Encodé à 17 im/s constants, le fichier dérivait de 6,6 s en 44 s
# pendant que le son restait exact. Le flux brut porte désormais chaque
# image à sa place réelle : répétée si la capture a été lente, sautée si
# elle a été rapide.

def test_une_capture_lente_est_completee_a_cadence_constante(tmp_path):
    rec = RecorderCore(resolution="160x120", fps=30, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    t0 = time.time()
    rec._t0 = t0
    for i in range(10):                         # 10 im/s réelles
        rec._write_frame(make_frame(), t=t0 + i * 0.1)
    rec._finalize_raw_video(t0 + 1.0)
    video_path, _ = rec.stop_recording()

    assert len(paquets(video_path)) == 30       # 1 s à 30 im/s
    assert rec._frame_count == 10               # images réellement captées


def test_une_capture_rapide_saute_des_images(tmp_path):
    rec = RecorderCore(resolution="160x120", fps=30, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    t0 = time.time()
    rec._t0 = t0
    for i in range(60):                         # 60 im/s réelles
        rec._write_frame(make_frame(), t=t0 + i / 60)
    rec._finalize_raw_video(t0 + 1.0)
    video_path, _ = rec.stop_recording()

    assert len(paquets(video_path)) == 30


def test_chaque_image_tient_jusqu_a_la_suivante(tmp_path):
    """L'image A captée à 0,5 s reste à l'écran jusqu'à B à 0,8 s, et
    tient depuis l'origine : le flux ne commence pas par un trou."""
    rec = RecorderCore(resolution="160x120", fps=30, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    t0 = time.time()
    rec._t0 = t0
    rec._write_frame(make_frame(value=0), t=t0 + 0.5)      # noire
    rec._write_frame(make_frame(value=255), t=t0 + 0.8)    # blanche
    rec._finalize_raw_video(t0 + 1.0)
    video_path, _ = rec.stop_recording()

    images = paquets(video_path)
    assert len(images) == 30
    noires = sum(1 for p in images if decoder(p).mean() < 50)
    blanches = sum(1 for p in images if decoder(p).mean() > 200)
    assert noires == 24                         # créneaux 0 à 23 (< 0,8 s)
    assert blanches == 6                        # créneaux 24 à 29


def test_la_duree_du_flux_egale_la_duree_reelle(tmp_path):
    """Quelle que soit la cadence de capture, le flux dure exactement
    le temps écoulé : c'est ce qui le garde aligné sur le son."""
    rec = RecorderCore(resolution="160x120", fps=25, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    t0 = time.time()
    rec._t0 = t0
    for t in (0.03, 0.9, 0.95, 1.0, 2.7):       # cadence chaotique
        rec._write_frame(make_frame(), t=t0 + t)
    rec._finalize_raw_video(t0 + 3.0)
    video_path, _ = rec.stop_recording()

    assert len(paquets(video_path)) == 75       # 3 s à 25 im/s


def test_stop_recording_finalise_le_flux_a_l_instant_de_l_arret(tmp_path):
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    t0 = time.time() - 1.0
    rec._t0 = t0
    rec._write_frame(make_frame(), t=t0)
    video_path, _ = rec.stop_recording()        # finalise à maintenant

    assert 10 <= len(paquets(video_path)) <= 12  # ~1 s à 10 im/s


def test_le_flux_brut_est_lu_par_ffmpeg_a_la_cadence_nominale(tmp_path):
    import json
    import shutil
    import subprocess

    if not shutil.which('ffprobe'):
        pytest.skip("ffprobe absent")

    rec = RecorderCore(resolution="160x120", fps=30, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    t0 = time.time()
    rec._t0 = t0
    for i in range(10):
        rec._write_frame(make_frame(), t=t0 + i * 0.1)
    rec._finalize_raw_video(t0 + 1.0)
    video_path, _ = rec.stop_recording()

    assert video_path.endswith('.mjpeg')
    sortie = subprocess.run(
        ['ffprobe', '-v', 'error', '-f', 'mjpeg', '-framerate', '30',
         '-count_frames', '-show_entries', 'stream=nb_read_frames',
         '-of', 'json', video_path],
        capture_output=True, text=True).stdout
    assert int(json.loads(sortie)['streams'][0]['nb_read_frames']) == 30


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


def test_origine_du_son_systeme_recalee_apres_l_attente_du_micro(tmp_path,
                                                                 monkeypatch):
    """Constaté en usage réel : sur un enregistrement avec le son
    système, la bande-son arrivait ~1 s AVANT l'image.

    Cause : _t0 servait d'origine au son système mais était posé avant
    l'attente de PortAudio (~1 s), alors que la vidéo ne démarre
    qu'après. get_audio_bytes réinsérait fidèlement ce silence en tête,
    décalant tout le son système. L'origine doit être prise juste avant
    que le son système et la vidéo ne partent ensemble."""
    reference = {}

    class FauxLoopback:
        def __init__(self, **kw):
            pass

        def start(self, reference_time=None):
            reference['t'] = reference_time
            reference['moment_du_demarrage'] = time.time()
            return True

        def stop(self):
            pass

    monkeypatch.setattr(recorder_core_module, 'SystemAudioCapture',
                        FauxLoopback)

    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=True,
                       system_audio_enabled=True)
    rec._temp_dir = str(tmp_path)

    # Micro lent à ouvrir, comme PortAudio en vrai
    def audio_lent(self):
        time.sleep(0.4)
        self._audio_ready.set()

    monkeypatch.setattr(RecorderCore, '_capture_audio', audio_lent)
    monkeypatch.setattr(RecorderCore, '_capture_screen',
                        lambda self: setattr(self, 'is_recording', False))

    rec.start_recording(str(tmp_path / "x.mp4"))
    time.sleep(0.1)
    rec.is_recording = False

    ecart = reference['moment_du_demarrage'] - reference['t']
    assert ecart < 0.15, (
        f"Le son système est daté {ecart:.2f} s avant son démarrage réel : "
        "il sortira en avance sur l'image")


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
