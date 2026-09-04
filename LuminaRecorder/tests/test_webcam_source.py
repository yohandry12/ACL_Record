"""Tests de la source webcam, avec une fausse cv2.VideoCapture.

Aucune caméra réelle n'est ouverte : le thread, la dernière image, les
erreurs et la libération sont vérifiés sur un double.
"""

import threading
import time

import numpy as np
import pytest

from core import webcam_source
from core.webcam_source import WebcamSource, lister_webcams


def attendre(condition, timeout=2.0):
    fin = time.time() + timeout
    while time.time() < fin:
        if condition():
            return True
        time.sleep(0.01)
    return False


class FausseCapture:
    """Rend des images numérotées : la N-ième vaut N partout."""

    def __init__(self, ouverte=True, images=None, echecs_apres=None):
        self.ouverte = ouverte
        self.compteur = 0
        self.echecs_apres = echecs_apres     # None = jamais d'échec
        self.liberee = False
        self.proprietes = {}

    def isOpened(self):
        return self.ouverte

    def set(self, prop, val):
        self.proprietes[prop] = val

    def read(self):
        if self.echecs_apres is not None and self.compteur >= self.echecs_apres:
            return False, None
        self.compteur += 1
        return True, np.full((480, 640, 3), self.compteur % 256, np.uint8)

    def release(self):
        self.liberee = True


def fabrique(capture):
    return lambda index: capture


def test_latest_rend_la_derniere_image_jamais_une_ancienne():
    capture = FausseCapture()
    source = WebcamSource(capture_factory=fabrique(capture))
    source.start()
    try:
        assert attendre(lambda: capture.compteur >= 5)
        image = source.latest()
        assert image is not None
        # L'image rendue est au plus une lecture derrière le compteur
        assert int(image[0, 0, 0]) >= (capture.compteur - 1) % 256
    finally:
        source.stop()


def test_latest_est_none_avant_la_premiere_image():
    source = WebcamSource(capture_factory=fabrique(FausseCapture()))
    assert source.latest() is None
    assert source.prete is False


def test_ouverture_echouee_renseigne_l_erreur():
    capture = FausseCapture(ouverte=False)
    source = WebcamSource(capture_factory=fabrique(capture))
    source.start()
    assert attendre(lambda: source.erreur != "")
    assert source.latest() is None
    assert capture.liberee is True
    source.stop()


def test_fabrique_qui_leve_ne_tue_pas_le_thread():
    def fabrique_cassee(index):
        raise RuntimeError("pilote absent")

    source = WebcamSource(capture_factory=fabrique_cassee)
    source.start()
    assert attendre(lambda: "pilote absent" in source.erreur)
    assert source.latest() is None
    source.stop()


def test_trois_lectures_ratees_arretent_la_source():
    capture = FausseCapture(echecs_apres=4)
    source = WebcamSource(capture_factory=fabrique(capture))
    source.start()
    assert attendre(lambda: source.erreur != "")
    assert "perdue" in source.erreur
    assert source.latest() is None          # plus d'image périmée
    assert capture.liberee is True
    assert attendre(lambda: not source._thread.is_alive())
    source.stop()


def test_stop_libere_la_camera_et_termine_le_thread():
    capture = FausseCapture()
    source = WebcamSource(capture_factory=fabrique(capture))
    source.start()
    assert attendre(lambda: capture.compteur >= 1)
    source.stop()
    assert capture.liberee is True
    assert not source._thread.is_alive()


def test_stop_sans_start_ne_leve_pas():
    WebcamSource(capture_factory=fabrique(FausseCapture())).stop()


class FausseCaptureBloquante:
    """Rend une première image puis bloque le deuxième read() jusqu'à
    ce que le test libère l'événement — simule un pilote qui ne rend
    pas la main à temps pour stop()."""

    def __init__(self):
        self.compteur = 0
        self.liberee = False
        self.bloque = threading.Event()     # posé une fois DANS le read() bloquant
        self.debloquer = threading.Event()

    def isOpened(self):
        return True

    def set(self, prop, val):
        pass

    def read(self):
        self.compteur += 1
        if self.compteur == 1:
            return True, np.full((480, 640, 3), 1, np.uint8)
        self.bloque.set()
        self.debloquer.wait()
        return True, np.full((480, 640, 3), 2, np.uint8)

    def release(self):
        self.liberee = True


def test_stop_avec_read_bloque_ne_publie_pas_d_image_tardive(monkeypatch):
    monkeypatch.setattr(WebcamSource, 'ARRET_TIMEOUT', 0.05)
    capture = FausseCaptureBloquante()
    source = WebcamSource(capture_factory=fabrique(capture))
    source.start()
    # Attend que le thread soit bien dans le read() bloquant (deuxième
    # appel) avant de stopper, pour ne pas dépendre d'un minutage fragile.
    assert attendre(lambda: capture.bloque.is_set())

    source.stop()
    assert source.latest() is None

    # Le pilote rend enfin la main : l'image tardive ne doit pas réapparaître
    capture.debloquer.set()
    assert attendre(lambda: not source._thread.is_alive())
    assert source.latest() is None
    assert capture.liberee is True


def test_la_resolution_demandee_est_appliquee():
    import cv2
    capture = FausseCapture()
    source = WebcamSource(largeur=1280, hauteur=720,
                          capture_factory=fabrique(capture))
    source.start()
    attendre(lambda: capture.compteur >= 1)
    source.stop()
    assert capture.proprietes[cv2.CAP_PROP_FRAME_WIDTH] == 1280
    assert capture.proprietes[cv2.CAP_PROP_FRAME_HEIGHT] == 720


# --- lister_webcams ---

def test_lister_webcams_associe_noms_et_index(monkeypatch):
    monkeypatch.setattr(webcam_source, '_noms_windows',
                        lambda: ["Integrated Webcam", "Logitech C920"])
    assert lister_webcams(rafraichir=True) == [
        {'index': 0, 'nom': "Integrated Webcam"},
        {'index': 1, 'nom': "Logitech C920"},
    ]


def test_lister_webcams_sans_camera_rend_une_liste_vide(monkeypatch):
    monkeypatch.setattr(webcam_source, '_noms_windows', lambda: [])
    assert lister_webcams(rafraichir=True) == []


def test_lister_webcams_ne_leve_jamais(monkeypatch):
    def casse():
        raise OSError("powershell introuvable")
    monkeypatch.setattr(webcam_source, '_noms_windows', casse)
    assert lister_webcams(rafraichir=True) == []


def test_lister_webcams_est_mis_en_cache(monkeypatch):
    appels = []
    monkeypatch.setattr(webcam_source, '_noms_windows',
                        lambda: appels.append(1) or ["Cam"])
    lister_webcams(rafraichir=True)
    lister_webcams()
    lister_webcams()
    assert len(appels) == 1


@pytest.mark.skipif(not lister_webcams(), reason="aucune webcam sur cette machine")
def test_une_vraie_webcam_donne_une_image_en_moins_de_5_s():
    source = WebcamSource(device_index=lister_webcams()[0]['index'])
    source.start()
    try:
        assert attendre(lambda: source.latest() is not None, timeout=5.0)
        assert source.latest().ndim == 3
    finally:
        source.stop()
