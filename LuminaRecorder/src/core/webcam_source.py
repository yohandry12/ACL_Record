"""
Lumina Recorder - Source webcam

Lit la caméra dans un thread dédié et garde la dernière image. Le filtre
d'incrustation vient la chercher sans jamais attendre : un `read()`
bloque 31 ms (mesuré sur la webcam intégrée), la boucle de capture n'a
pas ce temps.

La webcam ne fait jamais échouer un enregistrement : une ouverture
ratée ou une caméra perdue en route se traduisent par `erreur`
renseignée et `latest()` à None. C'est au filtre de dégrader.
"""

import subprocess
import threading
import time
from typing import Callable, List, Optional

import numpy as np

try:
    import cv2
except ImportError:      # pragma: no cover - cv2 est embarqué
    cv2 = None


def _ouvrir_camera(index: int):
    """Ouvre la caméra, DirectShow d'abord, Media Foundation en repli.

    Mesuré sur la webcam intégrée (ouverture + première image) :
    DSHOW ≈ 0,7 s contre ≈ 2,4 s pour MSMF. DSHOW est le backend
    historique, plus rapide à l'ouverture ; certaines caméras
    (pilotes récents, certaines webcams USB) ne s'exposent qu'en
    MSMF, d'où le repli si DSHOW échoue à s'ouvrir.
    """
    capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not capture.isOpened():
        capture.release()
        capture = cv2.VideoCapture(index, cv2.CAP_MSMF)
    return capture


class WebcamSource:
    """Dernière image de la caméra, lue dans un thread."""

    # Lectures ratées consécutives avant de déclarer la caméra perdue
    LECTURES_RATEES_MAX = 3

    # Délai laissé au thread pour sortir d'un read() bloqué lors du stop()
    ARRET_TIMEOUT = 2.0

    def __init__(self, device_index: int = 0, largeur: int = 640,
                 hauteur: int = 480,
                 capture_factory: Optional[Callable[[int], object]] = None):
        self.device_index = device_index
        self.largeur = largeur
        self.hauteur = hauteur
        self._capture_factory = capture_factory or _ouvrir_camera
        self._lock = threading.Lock()
        self._latest: Optional[np.ndarray] = None
        self._erreur = ""
        self._arret = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # --- lecture ---

    def start(self) -> None:
        """Lance le thread et rend la main aussitôt : l'ouverture mesurée
        est d'environ 1 s en DirectShow (≈ 2,4 s dans le repli Media
        Foundation), et le décompte de 3 s de l'enregistrement la
        couvre."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._boucle, daemon=True,
                                        name="lumina-webcam")
        self._thread.start()

    def _boucle(self) -> None:
        try:
            capture = self._capture_factory(self.device_index)
        except Exception as e:
            self._echouer(f"Webcam inaccessible : {e}")
            return

        try:
            if not capture.isOpened():
                self._echouer("Webcam introuvable ou déjà utilisée par "
                              "une autre application")
                return
            # Demande, sans garantie : la caméra choisit le plus proche
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.largeur)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.hauteur)

            ratees = 0
            while not self._arret.is_set():
                ok, image = capture.read()
                if not ok or image is None:
                    ratees += 1
                    if ratees >= self.LECTURES_RATEES_MAX:
                        self._echouer("Webcam perdue en cours "
                                      "d'enregistrement")
                        return
                    time.sleep(0.05)
                    continue
                ratees = 0
                with self._lock:
                    # Un stop() peut être arrivé pendant que read() bloquait :
                    # ne jamais écrire une image après coup, la caméra est
                    # censée être considérée arrêtée par l'appelant.
                    if self._arret.is_set():
                        break
                    self._latest = image
        finally:
            try:
                capture.release()
            except Exception:
                pass

    def _echouer(self, message: str) -> None:
        """Passe en erreur : plus d'image, même périmée."""
        with self._lock:
            self._erreur = message
            self._latest = None

    # --- lecture par le filtre et le pont ---

    def latest(self) -> Optional[np.ndarray]:
        """Dernière image BGR, ou None. Ne bloque jamais."""
        with self._lock:
            return self._latest

    @property
    def prete(self) -> bool:
        return self.latest() is not None

    @property
    def erreur(self) -> str:
        with self._lock:
            return self._erreur

    def stop(self) -> None:
        """Libère la caméra : la LED s'éteint, preuve visible.

        Si le pilote est bloqué dans read() au-delà d'ARRET_TIMEOUT, le
        thread reste vivant à la sortie de cette méthode ; _latest est
        tout de même effacé ici, et _boucle refusera d'y réécrire une
        image tardive une fois _arret posé — la libération réelle de la
        caméra n'a lieu que lorsque read() rend enfin la main."""
        self._arret.set()
        if self._thread is not None:
            self._thread.join(timeout=self.ARRET_TIMEOUT)
            if self._thread.is_alive():
                print("[Lumina] Webcam : le pilote ne rend pas la main, "
                      "libération différée")
        with self._lock:
            self._latest = None


# --- énumération ---

_cache_webcams: Optional[List[dict]] = None


def _noms_windows() -> List[str]:
    """Noms des caméras connues de Windows, dans l'ordre du système.

    PowerShell démarre en ~1 s : le résultat est mis en cache par
    lister_webcams. CREATE_NO_WINDOW évite le flash d'une console
    quand l'application tourne empaquetée sans console.
    """
    commande = ("Get-PnpDevice -Class Camera,Image -Status OK "
                "| Select-Object -ExpandProperty FriendlyName")
    sortie = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", commande],
        capture_output=True, text=True, timeout=8,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return [ligne.strip() for ligne in sortie.stdout.splitlines()
            if ligne.strip()]


def lister_webcams(rafraichir: bool = False) -> List[dict]:
    """Caméras disponibles : [{'index': 0, 'nom': 'Integrated Webcam'}].

    L'association nom → index OpenCV suit l'ordre du système ; elle
    n'est pas garantie, d'où le bouton « Tester » des réglages. Sans
    caméra, ou si Windows ne répond pas, la liste est vide et la
    fonction est simplement grisée : jamais d'exception.
    """
    global _cache_webcams
    if _cache_webcams is not None and not rafraichir:
        return list(_cache_webcams)
    try:
        noms = _noms_windows()
    except Exception as e:
        print(f"[Lumina] Webcams non listées : {e}")
        noms = []
    _cache_webcams = [{'index': i, 'nom': nom} for i, nom in enumerate(noms)]
    return list(_cache_webcams)
