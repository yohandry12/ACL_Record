# Incrustation webcam — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Incruster l'image de la webcam dans la vidéo enregistrée (forme, coin, taille, miroir choisis) et fournir au pont tout ce que la page a besoin : liste des caméras, test, aperçu pendant l'enregistrement.

**Architecture:** Un thread `WebcamSource` lit la caméra et garde la dernière image ; un `WebcamOverlayFilter` la compose dans chaque image capturée, en dernier de la chaîne de filtres ; le pont construit la source à l'enregistrement, la ferme à l'arrêt, et pousse une vignette JPEG à 8 im/s. **Ce plan ne touche pas à la page** (`index.html`, `app.js`) : elle est réécrite par le plan capsule, qui consomme l'API produite ici.

**Tech Stack:** Python 3, OpenCV (`cv2`, déjà embarqué), numpy, threading, pytest. Aucune dépendance ajoutée.

**Spec :** `docs/superpowers/specs/2026-09-04-webcam-incrustation-design.md`

## Global Constraints

- Tout en français : code, commentaires, docstrings, messages, commits.
- Zéro dépendance nouvelle : OpenCV, numpy, la bibliothèque standard.
- `[webcam] enabled = false` par défaut. Rien ne s'allume sans geste de l'utilisateur.
- La webcam ne fait **jamais** échouer ni interrompre un enregistrement : toute erreur dégrade en « image inchangée » et un avis unique.
- `latest()` ne bloque jamais ; aucun `read()` dans la boucle de capture.
- Le filtre webcam est **dernier** de la chaîne (après flou, après plugins).
- Coût du filtre : sous 2 ms pour une vignette « moyenne » sur 1366×768 (test à 2,5 ms pour absorber la variance de mesure).
- Formes : `rond`, `carre_arrondi`, `carre`. Coins : `haut-gauche`, `haut-droite`, `bas-gauche`, `bas-droite`. Tailles : `petite` 15 %, `moyenne` 22 %, `grande` 30 % de la hauteur. Marge 2 % de la largeur. Miroir activé par défaut.
- Aperçu : événement `webcam_preview`, JPEG 120×120 en base64, 8 im/s, uniquement en état `recording`.
- La webcam est libérée (LED éteinte) à l'arrêt, à l'annulation, sur erreur de capture et à la fermeture.
- Tests : `python -m pytest -q --ignore=tests/test_global_hotkey.py` doit rester vert (référence : 338 tests).
- Lancer les tests depuis `LuminaRecorder/` ; `tests/conftest.py` rend `src/` importable.

---

### Task 1 : `WebcamSource` — lecture de la caméra dans un thread

**Files:**
- Create: `LuminaRecorder/src/core/webcam_source.py`
- Test: `LuminaRecorder/tests/test_webcam_source.py`

**Interfaces:**
- Produces:
  - `WebcamSource(device_index: int = 0, largeur: int = 640, hauteur: int = 480, capture_factory=None)` ; `.start() -> None`, `.latest() -> Optional[np.ndarray]`, `.erreur -> str` (propriété), `.stop() -> None`, `.prete -> bool` (propriété : une image est disponible)
  - `lister_webcams(rafraichir: bool = False) -> List[dict]` : `[{'index': 0, 'nom': 'Integrated Webcam'}]`, liste vide si aucune caméra ou si Windows ne répond pas.
  - `capture_factory(index) -> objet` avec `.isOpened()`, `.read() -> (bool, image)`, `.set(prop, val)`, `.release()` — contrat de `cv2.VideoCapture`, injectable pour les tests.

- [ ] **Step 1 : Écrire les tests (échec attendu)**

```python
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
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd LuminaRecorder && python -m pytest tests/test_webcam_source.py -q`
Expected: erreur d'import `core.webcam_source`.

- [ ] **Step 3 : Implémenter la source**

```python
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


def _ouvrir_msmf(index: int):
    """Ouvre la caméra par Media Foundation, le backend natif Windows."""
    return cv2.VideoCapture(index, cv2.CAP_MSMF)


class WebcamSource:
    """Dernière image de la caméra, lue dans un thread."""

    # Lectures ratées consécutives avant de déclarer la caméra perdue
    LECTURES_RATEES_MAX = 3

    def __init__(self, device_index: int = 0, largeur: int = 640,
                 hauteur: int = 480,
                 capture_factory: Optional[Callable[[int], object]] = None):
        self.device_index = device_index
        self.largeur = largeur
        self.hauteur = hauteur
        self._capture_factory = capture_factory or _ouvrir_msmf
        self._lock = threading.Lock()
        self._latest: Optional[np.ndarray] = None
        self._erreur = ""
        self._arret = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # --- lecture ---

    def start(self) -> None:
        """Lance le thread et rend la main aussitôt : l'ouverture prend
        jusqu'à 3 s, le décompte de l'enregistrement les couvre."""
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
        """Libère la caméra : la LED s'éteint, preuve visible."""
        self._arret.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
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
```

- [ ] **Step 4 : Vérifier le succès**

Run: `cd LuminaRecorder && python -m pytest tests/test_webcam_source.py -q`
Expected: tous PASS (le test réel s'exécute si une webcam est branchée, sinon SKIP).

- [ ] **Step 5 : Commit**

```bash
git add LuminaRecorder/src/core/webcam_source.py LuminaRecorder/tests/test_webcam_source.py
git commit -m "feat: source webcam lue dans un thread, énumération des caméras"
```

---

### Task 2 : `WebcamOverlayFilter` — incrustation dans l'image

**Files:**
- Create: `LuminaRecorder/src/filters/webcam_overlay_filter.py`
- Test: `LuminaRecorder/tests/test_webcam_overlay_filter.py`

**Interfaces:**
- Consumes: un objet avec `.latest() -> Optional[np.ndarray]` (Task 1).
- Produces: `WebcamOverlayFilter(source, forme='rond', coin='bas-droite', taille='moyenne', miroir=True)`, `FrameFilter` de `name = "Webcam"` ; constantes de module `FORMES`, `COINS`, `TAILLES` (dict nom → ratio) ; `ValueError` sur valeur inconnue ; méthode `zone(frame_h, frame_w) -> (x, y, cote)` publique, utile aux tests et à l'aperçu.

- [ ] **Step 1 : Écrire les tests**

```python
"""Tests de l'incrustation webcam, sur images synthétiques."""

import time

import numpy as np
import pytest

from filters.webcam_overlay_filter import (COINS, FORMES, TAILLES,
                                           WebcamOverlayFilter)


class SourceFixe:
    def __init__(self, image):
        self.image = image

    def latest(self):
        return self.image


def image_webcam(couleur=(0, 0, 255)):
    """640×480 BGR unie ; par défaut rouge pur, facile à retrouver."""
    img = np.zeros((480, 640, 3), np.uint8)
    img[:] = couleur
    return img


def ecran(h=768, w=1366):
    return np.zeros((h, w, 3), np.uint8)


def test_sans_image_l_ecran_est_rendu_tel_quel():
    flt = WebcamOverlayFilter(SourceFixe(None))
    frame = ecran()
    assert flt.process(frame) is frame


def test_les_valeurs_inconnues_sont_refusees():
    with pytest.raises(ValueError):
        WebcamOverlayFilter(SourceFixe(None), forme='triangle')
    with pytest.raises(ValueError):
        WebcamOverlayFilter(SourceFixe(None), coin='milieu')
    with pytest.raises(ValueError):
        WebcamOverlayFilter(SourceFixe(None), taille='enorme')


@pytest.mark.parametrize('taille, ratio', list(TAILLES.items()))
def test_la_taille_est_une_fraction_de_la_hauteur(taille, ratio):
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()), taille=taille)
    _, _, cote = flt.zone(768, 1366)
    assert cote == int(768 * ratio)


@pytest.mark.parametrize('coin', COINS)
def test_chaque_coin_place_la_vignette_avec_la_marge(coin):
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()), coin=coin,
                              forme='carre', taille='petite')
    h, w = 768, 1366
    x, y, cote = flt.zone(h, w)
    marge = int(w * 0.02)
    attendu_x = marge if 'gauche' in coin else w - marge - cote
    attendu_y = marge if 'haut' in coin else h - marge - cote
    assert (x, y) == (attendu_x, attendu_y)

    sortie = flt.process(ecran(h, w))
    # Le centre de la zone est rouge (image webcam), le coin opposé noir
    assert tuple(sortie[y + cote // 2, x + cote // 2]) == (0, 0, 255)
    assert tuple(sortie[h - 1 - y if y < h // 2 else 0,
                        w - 1 - x if x < w // 2 else 0]) == (0, 0, 0)


def test_le_rond_laisse_les_coins_transparents():
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()), forme='rond',
                              coin='haut-gauche', taille='moyenne')
    frame = ecran()
    x, y, cote = flt.zone(*frame.shape[:2])
    sortie = flt.process(frame)
    assert tuple(sortie[y + cote // 2, x + cote // 2]) == (0, 0, 255)
    # Coin haut-gauche de la zone carrée : hors du disque, donc noir
    assert tuple(sortie[y + 1, x + 1]) == (0, 0, 0)


def test_le_carre_couvre_toute_la_zone():
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()), forme='carre',
                              coin='haut-gauche', taille='moyenne')
    frame = ecran()
    x, y, cote = flt.zone(*frame.shape[:2])
    sortie = flt.process(frame)
    # Bordure de 2 px exclue : on regarde 4 px à l'intérieur
    assert tuple(sortie[y + 4, x + 4]) == (0, 0, 255)


def test_le_carre_arrondi_coupe_les_coins_mais_pas_les_bords():
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()),
                              forme='carre_arrondi', coin='haut-gauche',
                              taille='moyenne')
    frame = ecran()
    x, y, cote = flt.zone(*frame.shape[:2])
    sortie = flt.process(frame)
    assert tuple(sortie[y + 1, x + 1]) == (0, 0, 0)
    assert tuple(sortie[y + cote // 2, x + 4]) == (0, 0, 255)


def test_la_bordure_est_dessinee_sur_le_pourtour():
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()), forme='carre',
                              coin='haut-gauche', taille='moyenne')
    frame = ecran()
    x, y, cote = flt.zone(*frame.shape[:2])
    sortie = flt.process(frame)
    pixel = tuple(int(v) for v in sortie[y + 1, x + cote // 2])
    assert pixel != (0, 0, 255) and pixel != (0, 0, 0)   # ni image ni fond


def test_le_miroir_inverse_horizontalement():
    img = image_webcam()
    img[:, :320] = (255, 0, 0)          # moitié gauche bleue, droite rouge
    frame = ecran()
    sans = WebcamOverlayFilter(SourceFixe(img), forme='carre',
                               coin='haut-gauche', miroir=False)
    avec = WebcamOverlayFilter(SourceFixe(img), forme='carre',
                               coin='haut-gauche', miroir=True)
    x, y, cote = sans.zone(*frame.shape[:2])
    a = sans.process(frame.copy())
    b = avec.process(frame.copy())
    assert tuple(a[y + cote // 2, x + 6]) == (255, 0, 0)
    assert tuple(b[y + cote // 2, x + 6]) == (0, 0, 255)


def test_une_image_4_3_est_recadree_au_centre():
    img = image_webcam()
    img[:, :80] = (0, 255, 0)           # bandes vertes gauche/droite
    img[:, -80:] = (0, 255, 0)
    flt = WebcamOverlayFilter(SourceFixe(img), forme='carre',
                              coin='haut-gauche', miroir=False)
    frame = ecran()
    x, y, cote = flt.zone(*frame.shape[:2])
    sortie = flt.process(frame)
    # Recadrage 480×480 centré : les bandes vertes sont hors champ
    assert tuple(sortie[y + cote // 2, x + 4]) == (0, 0, 255)
    assert tuple(sortie[y + cote // 2, x + cote - 5]) == (0, 0, 255)


def test_le_cout_reste_sous_le_budget():
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()), taille='moyenne')
    frame = ecran()
    for _ in range(20):
        flt.process(frame.copy())      # chauffe et remplit le cache
    debut = time.perf_counter()
    n = 200
    for _ in range(n):
        flt.process(frame)
    moyenne_ms = (time.perf_counter() - debut) / n * 1000
    assert moyenne_ms < 2.5, f"{moyenne_ms:.2f} ms par image"
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd LuminaRecorder && python -m pytest tests/test_webcam_overlay_filter.py -q`
Expected: erreur d'import.

- [ ] **Step 3 : Implémenter le filtre**

```python
"""
Lumina Filters - Incrustation de la webcam

Compose la dernière image de la caméra dans un coin de chaque image
capturée, découpée selon une forme. Dernier filtre de la chaîne : après
le flou de confidentialité (sinon l'OCR flouterait le visage) et après
les plugins.

Coût maîtrisé : masques calculés une fois par (forme, côté) et mis en
cache ; composition sur la seule zone de la vignette. Mesuré sous 2 ms
pour une vignette « moyenne » sur 1366×768.
"""

from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from .base import FrameFilter

FORMES = ('rond', 'carre_arrondi', 'carre')
COINS = ('haut-gauche', 'haut-droite', 'bas-gauche', 'bas-droite')
TAILLES = {'petite': 0.15, 'moyenne': 0.22, 'grande': 0.30}

# Accent ambre de l'interface (#F59E0B), en BGR pour OpenCV
BORDURE_BGR = (11, 158, 245)
BORDURE_PX = 2
# Ombre douce sous la vignette : décalage vertical et rayon de flou
OMBRE_DECALAGE = 4
OMBRE_RAYON = 6
OMBRE_OPACITE = 0.45
MARGE_RATIO = 0.02


class WebcamOverlayFilter(FrameFilter):
    name = "Webcam"

    def __init__(self, source, forme: str = 'rond', coin: str = 'bas-droite',
                 taille: str = 'moyenne', miroir: bool = True):
        super().__init__()
        if forme not in FORMES:
            raise ValueError(f"Forme inconnue : {forme}")
        if coin not in COINS:
            raise ValueError(f"Coin inconnu : {coin}")
        if taille not in TAILLES:
            raise ValueError(f"Taille inconnue : {taille}")
        self.source = source
        self.forme = forme
        self.coin = coin
        self.taille = taille
        self.miroir = miroir
        # (forme, cote) -> (masque HxWx1 float32, ombre HxWx1 float32)
        self._cache: Dict[Tuple[str, int], Tuple[np.ndarray, np.ndarray]] = {}

    # --- géométrie ---

    def zone(self, frame_h: int, frame_w: int) -> Tuple[int, int, int]:
        """(x, y, côté) de la vignette dans une image de cette taille."""
        cote = int(frame_h * TAILLES[self.taille])
        marge = int(frame_w * MARGE_RATIO)
        x = marge if 'gauche' in self.coin else frame_w - marge - cote
        y = marge if 'haut' in self.coin else frame_h - marge - cote
        return x, y, cote

    # --- masques ---

    def _masques(self, cote: int) -> Tuple[np.ndarray, np.ndarray]:
        cle = (self.forme, cote)
        if cle not in self._cache:
            forme = np.zeros((cote, cote), np.uint8)
            if self.forme == 'rond':
                cv2.circle(forme, (cote // 2, cote // 2), cote // 2 - 1, 255, -1)
            elif self.forme == 'carre_arrondi':
                r = max(4, cote // 6)
                cv2.rectangle(forme, (r, 0), (cote - 1 - r, cote - 1), 255, -1)
                cv2.rectangle(forme, (0, r), (cote - 1, cote - 1 - r), 255, -1)
                for cx, cy in ((r, r), (cote - 1 - r, r),
                               (r, cote - 1 - r), (cote - 1 - r, cote - 1 - r)):
                    cv2.circle(forme, (cx, cy), r, 255, -1)
            else:
                forme[:] = 255
            masque = (forme.astype(np.float32) / 255.0)[:, :, None]

            # Ombre : la forme, décalée vers le bas et floutée, sur un
            # canevas assez grand pour le décalage et le flou
            taille_ombre = cote + 2 * OMBRE_RAYON + OMBRE_DECALAGE
            ombre = np.zeros((taille_ombre, taille_ombre), np.uint8)
            ombre[OMBRE_RAYON + OMBRE_DECALAGE:OMBRE_RAYON + OMBRE_DECALAGE + cote,
                  OMBRE_RAYON:OMBRE_RAYON + cote] = forme
            ombre = cv2.GaussianBlur(ombre, (0, 0), OMBRE_RAYON / 2)
            ombre = (ombre.astype(np.float32) / 255.0 * OMBRE_OPACITE)[:, :, None]
            self._cache[cle] = (masque, ombre)
        return self._cache[cle]

    # --- image webcam ---

    def _vignette(self, image: np.ndarray, cote: int) -> np.ndarray:
        """Recadre au carré centré, redimensionne, applique le miroir et
        dessine la bordure dans la forme."""
        h, w = image.shape[:2]
        c = min(h, w)
        y0, x0 = (h - c) // 2, (w - c) // 2
        carre = image[y0:y0 + c, x0:x0 + c]
        vignette = cv2.resize(carre, (cote, cote), interpolation=cv2.INTER_AREA)
        if self.miroir:
            vignette = cv2.flip(vignette, 1)
        if self.forme == 'rond':
            cv2.circle(vignette, (cote // 2, cote // 2), cote // 2 - 1,
                       BORDURE_BGR, BORDURE_PX)
        elif self.forme == 'carre_arrondi':
            # Contour approché par le rectangle : lisible, et bien
            # moins cher qu'un tracé de coins arrondis par image
            cv2.rectangle(vignette, (0, 0), (cote - 1, cote - 1),
                          BORDURE_BGR, BORDURE_PX)
        else:
            cv2.rectangle(vignette, (0, 0), (cote - 1, cote - 1),
                          BORDURE_BGR, BORDURE_PX)
        return vignette

    # --- composition ---

    def process(self, frame: np.ndarray) -> np.ndarray:
        image = self.source.latest()
        if image is None:
            return frame          # webcam absente : image inchangée

        h, w = frame.shape[:2]
        x, y, cote = self.zone(h, w)
        if cote < 8 or x < 0 or y < 0:
            return frame
        masque, ombre = self._masques(cote)

        # Ombre, sur une zone un peu plus large que la vignette, bornée
        # à l'image
        ox0, oy0 = x - OMBRE_RAYON, y - OMBRE_RAYON
        ox1, oy1 = ox0 + ombre.shape[1], oy0 + ombre.shape[0]
        sx0, sy0 = max(0, ox0), max(0, oy0)
        sx1, sy1 = min(w, ox1), min(h, oy1)
        if sx1 > sx0 and sy1 > sy0:
            part = ombre[sy0 - oy0:sy1 - oy0, sx0 - ox0:sx1 - ox0]
            zone_ombre = frame[sy0:sy1, sx0:sx1]
            zone_ombre[:] = (zone_ombre * (1.0 - part)).astype(np.uint8)

        vignette = self._vignette(image, cote)
        zone = frame[y:y + cote, x:x + cote]
        zone[:] = (vignette * masque + zone * (1.0 - masque)).astype(np.uint8)
        return frame
```

- [ ] **Step 4 : Vérifier le succès**

Run: `cd LuminaRecorder && python -m pytest tests/test_webcam_overlay_filter.py -q`
Expected: tous PASS. Si `test_le_cout_reste_sous_le_budget` échoue, mesurer d'abord (`print(moyenne_ms)`) : la cause habituelle est la conversion float sur toute la zone — vérifier que `masque` est bien en `float32` et pas `float64`.

- [ ] **Step 5 : Commit**

```bash
git add LuminaRecorder/src/filters/webcam_overlay_filter.py LuminaRecorder/tests/test_webcam_overlay_filter.py
git commit -m "feat: filtre d'incrustation webcam (formes, coins, tailles, miroir)"
```

---

### Task 3 : Réglages `[webcam]` et place dans la chaîne de filtres

**Files:**
- Create: `LuminaRecorder/src/core/webcam_options.py`
- Modify: `LuminaRecorder/src/core/ai_options.py:62-81` (`build_filters`)
- Modify: `LuminaRecorder/config/default_config.ini` (section `[webcam]`)
- Test: `LuminaRecorder/tests/test_webcam_options.py`, `LuminaRecorder/tests/test_ai_options_config.py`

**Interfaces:**
- Consumes: `WebcamOverlayFilter`, `FORMES`, `COINS`, `TAILLES` (Task 2).
- Produces:
  - `WebcamOptions.SECTION = 'webcam'`, `WebcamOptions.DEFAUTS` (dict), `WebcamOptions.load(config) -> dict` avec clés `enabled: bool, device: int, forme: str, coin: str, taille: str, miroir: bool` (valeurs invalides ramenées au défaut), `WebcamOptions.build_filter(options: dict, source) -> WebcamOverlayFilter`.
  - `AIOptions.build_filters(options, plugins_actifs=None, webcam_filter=None)` : `webcam_filter` ajouté **en dernier** s'il n'est pas `None`.

- [ ] **Step 1 : Tests des options**

```python
"""Tests des réglages webcam : valeurs par défaut, assainissement."""

from utils.config_manager import ConfigManager
from core.webcam_options import WebcamOptions
from filters.webcam_overlay_filter import WebcamOverlayFilter


def make_config(tmp_path):
    return ConfigManager(config_path=str(tmp_path / "t.ini"))


def test_desactive_par_defaut(tmp_path):
    opts = WebcamOptions.load(make_config(tmp_path))
    assert opts == {'enabled': False, 'device': 0, 'forme': 'rond',
                    'coin': 'bas-droite', 'taille': 'moyenne',
                    'miroir': True}


def test_lecture_des_valeurs_ecrites(tmp_path):
    cfg = make_config(tmp_path)
    cfg.set('webcam', 'enabled', True)
    cfg.set('webcam', 'device', 2)
    cfg.set('webcam', 'forme', 'carre')
    cfg.set('webcam', 'coin', 'haut-gauche')
    cfg.set('webcam', 'taille', 'grande')
    cfg.set('webcam', 'miroir', False)
    opts = WebcamOptions.load(cfg)
    assert opts == {'enabled': True, 'device': 2, 'forme': 'carre',
                    'coin': 'haut-gauche', 'taille': 'grande',
                    'miroir': False}


def test_une_valeur_invalide_revient_au_defaut(tmp_path):
    """Un .ini édité à la main ne doit jamais empêcher d'enregistrer."""
    cfg = make_config(tmp_path)
    cfg.set('webcam', 'forme', 'hexagone')
    cfg.set('webcam', 'coin', 'centre')
    cfg.set('webcam', 'taille', 'xxl')
    cfg.set('webcam', 'device', 'abc')
    opts = WebcamOptions.load(cfg)
    assert opts['forme'] == 'rond'
    assert opts['coin'] == 'bas-droite'
    assert opts['taille'] == 'moyenne'
    assert opts['device'] == 0


def test_build_filter_transmet_les_reglages():
    class Source:
        def latest(self):
            return None
    src = Source()
    flt = WebcamOptions.build_filter(
        {'enabled': True, 'device': 0, 'forme': 'carre_arrondi',
         'coin': 'haut-droite', 'taille': 'petite', 'miroir': False}, src)
    assert isinstance(flt, WebcamOverlayFilter)
    assert flt.source is src
    assert (flt.forme, flt.coin, flt.taille, flt.miroir) == (
        'carre_arrondi', 'haut-droite', 'petite', False)
```

Ajouter à `tests/test_ai_options_config.py` :

```python
def test_le_filtre_webcam_est_dernier_de_la_chaine(monkeypatch):
    """Après le flou (sinon l'OCR flouterait le visage) et après les
    plugins : la vignette se pose sur une image finie."""
    from core import ai_options
    from filters.base import FrameFilter
    from filters.webcam_overlay_filter import WebcamOverlayFilter

    class FauxPlugin(FrameFilter):
        name = "Faux"

        def process(self, frame):
            return frame

    class Source:
        def latest(self):
            return None

    monkeypatch.setattr(ai_options, 'lister_plugins',
                        lambda: [_info_plugin()])
    monkeypatch.setattr(ai_options, 'charger_plugin', lambda i: FauxPlugin())
    webcam = WebcamOverlayFilter(Source())

    filtres = AIOptions.build_filters({'clean_canvas': True},
                                      plugins_actifs=['faux'],
                                      webcam_filter=webcam)

    assert filtres[-1] is webcam
    assert len(filtres) == 3


def test_sans_filtre_webcam_la_chaine_est_inchangee():
    filtres = AIOptions.build_filters({'clean_canvas': True},
                                      webcam_filter=None)
    assert len(filtres) == 1
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd LuminaRecorder && python -m pytest tests/test_webcam_options.py tests/test_ai_options_config.py -q`
Expected: import de `core.webcam_options` en échec ; `build_filters() got an unexpected keyword argument 'webcam_filter'`.

- [ ] **Step 3 : Implémenter**

`src/core/webcam_options.py` :

```python
"""
Lumina Recorder - Réglages de la webcam

Section [webcam] du .ini. Désactivée par défaut : rien ne s'allume sans
le choix de l'utilisateur. Les valeurs invalides (fichier édité à la
main) reviennent au défaut plutôt que d'empêcher d'enregistrer.
"""

from filters.webcam_overlay_filter import (COINS, FORMES, TAILLES,
                                           WebcamOverlayFilter)


class WebcamOptions:
    SECTION = 'webcam'
    DEFAUTS = {
        'enabled': False,
        'device': 0,
        'forme': 'rond',
        'coin': 'bas-droite',
        'taille': 'moyenne',
        'miroir': True,
    }

    @staticmethod
    def load(config) -> dict:
        s = WebcamOptions.SECTION
        d = WebcamOptions.DEFAUTS
        forme = config.get(s, 'forme', fallback=d['forme'])
        coin = config.get(s, 'coin', fallback=d['coin'])
        taille = config.get(s, 'taille', fallback=d['taille'])
        return {
            'enabled': config.get_bool(s, 'enabled', fallback=d['enabled']),
            'device': max(0, config.get_int(s, 'device', fallback=d['device'])),
            'forme': forme if forme in FORMES else d['forme'],
            'coin': coin if coin in COINS else d['coin'],
            'taille': taille if taille in TAILLES else d['taille'],
            'miroir': config.get_bool(s, 'miroir', fallback=d['miroir']),
        }

    @staticmethod
    def build_filter(options: dict, source) -> WebcamOverlayFilter:
        return WebcamOverlayFilter(source, forme=options['forme'],
                                   coin=options['coin'],
                                   taille=options['taille'],
                                   miroir=options['miroir'])
```

Dans `ai_options.py`, remplacer la signature et la fin de `build_filters` :

```python
    @staticmethod
    def build_filters(options: dict, plugins_actifs=None,
                      webcam_filter=None) -> list:
        filters = []
        # Sans moteur OCR, le flou n'a aucune zone à masquer : on n'ajoute
        # pas un filtre inerte, même si le .ini garde la valeur d'une
        # session où easyocr était installé
        if options.get('privacy_blur') and ocr_is_available():
            filters.append(PrivacyBlurFilter())
        if options.get('clean_canvas'):
            filters.append(CleanCanvasFilter())
        if options.get('overlay'):
            filters.append(OverlayFilter())

        # Plugins de l'utilisateur, APRÈS les filtres natifs : ils
        # travaillent sur une image déjà nettoyée. Un plugin qui refuse
        # de se charger est simplement absent — jamais une exception,
        # sinon un fichier tiers défectueux empêcherait d'enregistrer.
        # Seuls les FrameFilter sont retenus : un post-traitement activé
        # n'a rien à faire dans la chaîne temps réel.
        filters.extend(AIOptions._plugins_filtres(plugins_actifs))

        # La webcam en tout dernier : après le flou, sinon l'OCR
        # flouterait le visage ; après les plugins, pour que la vignette
        # se pose sur une image finie
        if webcam_filter is not None:
            filters.append(webcam_filter)
        return filters
```

Dans `config/default_config.ini`, ajouter à la fin :

```ini
[webcam]
# Incrustation du visage. Jamais activée sans choix explicite.
enabled = false
device = 0
forme = rond
coin = bas-droite
taille = moyenne
miroir = true
```

- [ ] **Step 4 : Vérifier le succès**

Run: `cd LuminaRecorder && python -m pytest tests/test_webcam_options.py tests/test_ai_options_config.py -q`
Expected: PASS.

- [ ] **Step 5 : Commit**

```bash
git add LuminaRecorder/src/core/webcam_options.py LuminaRecorder/src/core/ai_options.py LuminaRecorder/config/default_config.ini LuminaRecorder/tests/test_webcam_options.py LuminaRecorder/tests/test_ai_options_config.py
git commit -m "feat: réglages [webcam] et filtre webcam en fin de chaîne"
```

---

### Task 4 : Pont — cycle de vie de la webcam, API pour la page, aperçu

**Files:**
- Modify: `LuminaRecorder/src/webui/bridge.py` (imports, `__init__`, `SIMPLE_KEYS`, `get_initial_state`, `start_recording`, `_launch`, `stop_recording`, `_finish`, `shutdown` ; nouvelles méthodes)
- Test: `LuminaRecorder/tests/test_bridge.py` (fixture `FakeWebcam`, tests ajoutés)

**Interfaces:**
- Consumes: `WebcamSource`, `lister_webcams` (Task 1) ; `WebcamOptions` (Task 3) ; `AIOptions.build_filters(..., webcam_filter=)` (Task 3).
- Produces (API vue par la page) :
  - `set_option` accepte `webcam_enabled`, `webcam_device`, `webcam_forme`, `webcam_coin`, `webcam_taille`, `webcam_miroir`.
  - `get_initial_state()['webcam'] == {'enabled', 'device', 'forme', 'coin', 'taille', 'miroir', 'available': bool, 'devices': [{'index', 'nom'}]}`.
  - `get_webcams() -> {'ok': True, 'webcams': [...]}` (relit la liste).
  - `test_webcam(index: int) -> {'ok': True, 'image': '<base64 JPEG 240×240>'}` ou `{'ok': False, 'error': str}` ; bloque au plus 5 s ; refusé pendant un enregistrement.
  - événement `webcam_preview` : `{'image': '<base64 JPEG 120×120>'}` à 8 im/s en `recording`.
  - événement `notice` : `"Webcam indisponible : … — enregistrement sans elle"` au démarrage si la source est en erreur ; `"Webcam perdue, enregistrement poursuivi sans elle"` une seule fois en cours.
  - attributs injectables : `bridge._webcam_factory` (défaut `WebcamSource`), `bridge._lister_webcams` (défaut `lister_webcams`).

- [ ] **Step 1 : Tests**

Ajouter à `tests/test_bridge.py`, après la classe `FakeAnalyzer` :

```python
class FakeWebcam:
    """Source webcam factice : image immédiate, ou erreur à la demande."""
    instances = []

    def __init__(self, device_index=0, erreur="", **kwargs):
        import numpy as np
        FakeWebcam.instances.append(self)
        self.device_index = device_index
        self._erreur = erreur
        self.demarree = False
        self.arretee = False
        self.image = None if erreur else np.zeros((480, 640, 3), np.uint8)

    def start(self):
        self.demarree = True

    def latest(self):
        return None if self.arretee else self.image

    @property
    def prete(self):
        return self.latest() is not None

    @property
    def erreur(self):
        return self._erreur

    def stop(self):
        self.arretee = True
```

Dans la fixture `bridge`, après `b._window = FakeWindow()` :

```python
    FakeWebcam.instances.clear()
    b._webcam_factory = FakeWebcam
    b._lister_webcams = lambda rafraichir=False: [
        {'index': 0, 'nom': "Cam de test"}]
```

Puis, en fin de fichier :

```python
# --- webcam ---

def activer_webcam(bridge):
    bridge.config.set('webcam', 'enabled', True)


def test_l_etat_initial_decrit_la_webcam(bridge):
    etat = bridge.get_initial_state()['webcam']
    assert set(etat) == {'enabled', 'device', 'forme', 'coin', 'taille',
                         'miroir', 'available', 'devices'}
    assert etat['enabled'] is False
    assert etat['available'] is True
    assert etat['devices'] == [{'index': 0, 'nom': "Cam de test"}]


def test_sans_camera_la_webcam_est_indisponible(bridge):
    bridge._lister_webcams = lambda rafraichir=False: []
    assert bridge.get_initial_state()['webcam']['available'] is False


def test_les_reglages_webcam_sont_persistes(bridge):
    for cle, valeur, ini in (('webcam_enabled', True, 'enabled'),
                             ('webcam_device', 1, 'device'),
                             ('webcam_forme', 'carre', 'forme'),
                             ('webcam_coin', 'haut-gauche', 'coin'),
                             ('webcam_taille', 'grande', 'taille'),
                             ('webcam_miroir', False, 'miroir')):
        assert bridge.set_option(cle, valeur)['ok'] is True
        assert ('webcam', ini, valeur) in bridge.config.saved


def test_webcam_desactivee_aucune_source_n_est_creee(bridge, monkeypatch):
    demarrer_sans_attendre(bridge, monkeypatch)
    assert FakeWebcam.instances == []
    filtres = bridge.recorder.kwargs['filters']
    assert all(f.name != "Webcam" for f in filtres)


def test_webcam_activee_la_source_est_ouverte_avant_la_capture(bridge,
                                                                 monkeypatch):
    activer_webcam(bridge)
    bridge.config.set('webcam', 'device', 1)
    demarrer_sans_attendre(bridge, monkeypatch)

    assert len(FakeWebcam.instances) == 1
    source = FakeWebcam.instances[0]
    assert source.demarree is True
    assert source.device_index == 1
    # Le filtre webcam est le dernier de la chaîne transmise au moteur
    filtres = bridge.recorder.kwargs['filters']
    assert filtres and filtres[-1].name == "Webcam"
    assert filtres[-1].source is source


def test_la_webcam_est_liberee_a_l_arret(bridge, monkeypatch):
    activer_webcam(bridge)
    demarrer_sans_attendre(bridge, monkeypatch)
    bridge.stop_recording()
    assert attendre(lambda: bridge.state == IDLE)
    assert FakeWebcam.instances[0].arretee is True
    assert bridge._webcam is None


def test_la_webcam_est_liberee_si_le_decompte_est_annule(bridge):
    activer_webcam(bridge)
    bridge.start_recording()
    bridge.stop_recording()
    assert FakeWebcam.instances[0].arretee is True


def test_la_webcam_est_liberee_si_le_moteur_refuse(bridge, monkeypatch):
    activer_webcam(bridge)
    monkeypatch.setattr(FakeRecorder, 'start_recording',
                        lambda self, path: False)
    monkeypatch.setattr(bridge, 'COUNTDOWN_SECONDS', 0, raising=False)
    monkeypatch.setattr(bridge_module.time, 'sleep', lambda s: None)
    bridge.start_recording()
    assert attendre(lambda: bridge.state == IDLE)
    assert FakeWebcam.instances[0].arretee is True


def test_la_webcam_est_liberee_a_la_fermeture(bridge, monkeypatch):
    activer_webcam(bridge)
    demarrer_sans_attendre(bridge, monkeypatch)
    bridge.shutdown()
    assert FakeWebcam.instances[0].arretee is True


def test_une_webcam_en_erreur_n_empeche_pas_d_enregistrer(bridge,
                                                          monkeypatch):
    activer_webcam(bridge)
    bridge._webcam_factory = lambda **kw: FakeWebcam(erreur="occupée", **kw)
    demarrer_sans_attendre(bridge, monkeypatch)

    assert bridge.state == RECORDING
    avis = bridge._window.events_named('notice')
    assert any('Webcam indisponible' in a for a in avis)


def test_une_fabrique_qui_leve_n_empeche_pas_d_enregistrer(bridge,
                                                           monkeypatch):
    activer_webcam(bridge)

    def cassee(**kw):
        raise RuntimeError("pas de pilote")
    bridge._webcam_factory = cassee
    demarrer_sans_attendre(bridge, monkeypatch)

    assert bridge.state == RECORDING
    assert bridge._webcam is None


def test_l_apercu_est_pousse_pendant_l_enregistrement(bridge, monkeypatch):
    activer_webcam(bridge)
    demarrer_sans_attendre(bridge, monkeypatch)
    assert attendre(lambda: bridge._window.events_named('webcam_preview'))
    envoye = bridge._window.events_named('webcam_preview')[0]
    assert '"image"' in envoye
    bridge.stop_recording()
    attendre(lambda: bridge.state == IDLE)
    combien = len(bridge._window.events_named('webcam_preview'))
    time.sleep(0.3)
    # Plus rien après l'arrêt
    assert len(bridge._window.events_named('webcam_preview')) == combien


def test_aucun_apercu_sans_webcam(bridge, monkeypatch):
    demarrer_sans_attendre(bridge, monkeypatch)
    time.sleep(0.3)
    assert bridge._window.events_named('webcam_preview') == []


def test_une_webcam_perdue_est_signalee_une_seule_fois(bridge, monkeypatch):
    activer_webcam(bridge)
    demarrer_sans_attendre(bridge, monkeypatch)
    source = FakeWebcam.instances[0]
    source.image = None
    source._erreur = "Webcam perdue en cours d'enregistrement"
    assert attendre(lambda: any('perdue' in a for a in
                                bridge._window.events_named('notice')))
    time.sleep(0.4)
    assert sum('perdue' in a for a in
               bridge._window.events_named('notice')) == 1
    assert bridge.state == RECORDING


def test_get_webcams_relit_la_liste(bridge):
    appels = []
    bridge._lister_webcams = lambda rafraichir=False: appels.append(
        rafraichir) or [{'index': 0, 'nom': "Cam"}]
    resultat = bridge.get_webcams()
    assert resultat == {'ok': True, 'webcams': [{'index': 0, 'nom': "Cam"}]}
    assert appels == [True]


def test_test_webcam_rend_une_image(bridge):
    resultat = bridge.test_webcam(0)
    assert resultat['ok'] is True
    assert isinstance(resultat['image'], str) and len(resultat['image']) > 100
    assert FakeWebcam.instances[0].arretee is True


def test_test_webcam_signale_l_erreur(bridge):
    bridge._webcam_factory = lambda **kw: FakeWebcam(erreur="occupée", **kw)
    resultat = bridge.test_webcam(0)
    assert resultat['ok'] is False
    assert 'occupée' in resultat['error']


def test_test_webcam_refuse_pendant_l_enregistrement(bridge, monkeypatch):
    demarrer_sans_attendre(bridge, monkeypatch)
    resultat = bridge.test_webcam(0)
    assert resultat['ok'] is False
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `cd LuminaRecorder && python -m pytest tests/test_bridge.py -q -k webcam`
Expected: échecs (`KeyError: 'webcam'`, attributs absents).

- [ ] **Step 3 : Implémenter dans `bridge.py`**

Imports (près des autres imports `core.`) :

```python
import base64

from core.webcam_options import WebcamOptions
from core.webcam_source import WebcamSource, lister_webcams
```

Dans `__init__`, après `self._update_downloader = download_setup` :

```python
        # Webcam : la source vit le temps d'un enregistrement (ou d'un
        # test). Fabrique et énumération injectables pour les tests.
        self._webcam = None
        self._webcam_factory = WebcamSource
        self._lister_webcams = lister_webcams
        self._webcam_perdue_signalee = False
```

Dans `SIMPLE_KEYS`, ajouter :

```python
        'webcam_enabled': ('webcam', 'enabled'),
        'webcam_device': ('webcam', 'device'),
        'webcam_forme': ('webcam', 'forme'),
        'webcam_coin': ('webcam', 'coin'),
        'webcam_taille': ('webcam', 'taille'),
        'webcam_miroir': ('webcam', 'miroir'),
```

Dans `get_initial_state`, ajouter la clé `'webcam'` au dictionnaire rendu (après `'ai'`) :

```python
            'webcam': self._etat_webcam(),
```

et la méthode :

```python
    def _etat_webcam(self) -> dict:
        """Réglages et caméras présentes. Sans caméra, la page grise la
        section avec la raison plutôt que d'offrir une case inerte."""
        try:
            devices = self._lister_webcams()
        except Exception:
            devices = []
        etat = WebcamOptions.load(self.config)
        etat['available'] = bool(devices)
        etat['devices'] = devices
        return etat
```

Dans `start_recording`, **avant** `self.recorder = self._recorder_factory(` :

```python
            webcam_filter = self._ouvrir_webcam()
```

et passer `filters=AIOptions.build_filters(options, plugins_actifs=self._plugins_actifs(), webcam_filter=webcam_filter)`.

Nouvelles méthodes (section « Webcam », avant « Raccourci global ») :

```python
    # ------------------------------------------------------------------
    # Webcam
    # ------------------------------------------------------------------

    def _ouvrir_webcam(self):
        """Ouvre la caméra si l'utilisateur l'a demandée et rend le
        filtre à placer en fin de chaîne, ou None.

        Appelé AVANT la construction du recorder, donc avant le décompte :
        l'ouverture prend jusqu'à 3 s, le décompte les couvre. Un échec
        ici ne bloque jamais l'enregistrement : on continue sans vignette.
        """
        self._webcam_perdue_signalee = False
        options = WebcamOptions.load(self.config)
        if not options['enabled']:
            return None
        try:
            self._webcam = self._webcam_factory(device_index=options['device'])
            self._webcam.start()
            return WebcamOptions.build_filter(options, self._webcam)
        except Exception as e:
            print(f"[Lumina] Webcam non ouverte : {e}")
            self._fermer_webcam()
            return None

    def _fermer_webcam(self):
        """Libère la caméra ; la LED s'éteint. Sans effet si absente."""
        source, self._webcam = self._webcam, None
        if source is not None:
            try:
                source.stop()
            except Exception as e:
                print(f"[Lumina] Webcam non libérée : {e}")

    def _annoncer_webcam_absente(self):
        """Au démarrage réel : si la caméra est déjà en erreur, le dire."""
        if self._webcam is not None and self._webcam.erreur:
            self.emit('notice', f"Webcam indisponible : {self._webcam.erreur}"
                                " — enregistrement sans elle")
            self._webcam_perdue_signalee = True

    APERCU_COTE = 120
    APERCU_PAR_SECONDE = 8

    def _start_webcam_preview(self):
        """Pousse une vignette JPEG vers le widget à 8 im/s, depuis un
        thread : ~6 Ko par image, rien n'est écrit sur disque."""
        if self._webcam is None:
            return
        source = self._webcam
        miroir = WebcamOptions.load(self.config)['miroir']

        def run():
            intervalle = 1.0 / self.APERCU_PAR_SECONDE
            while self.state == RECORDING and self._webcam is source:
                image = source.latest()
                if image is None:
                    if source.erreur and not self._webcam_perdue_signalee:
                        self._webcam_perdue_signalee = True
                        self.emit('notice', "Webcam perdue, enregistrement "
                                            "poursuivi sans elle")
                else:
                    encode = self._vignette_base64(image, self.APERCU_COTE,
                                                   miroir)
                    if encode:
                        self.emit('webcam_preview', {'image': encode})
                time.sleep(intervalle)

        threading.Thread(target=run, daemon=True,
                         name="lumina-webcam-apercu").start()

    @staticmethod
    def _vignette_base64(image, cote: int, miroir: bool) -> str:
        """Carré centré de `cote` px, JPEG qualité 70, en base64."""
        try:
            import cv2
            h, w = image.shape[:2]
            c = min(h, w)
            carre = image[(h - c) // 2:(h - c) // 2 + c,
                          (w - c) // 2:(w - c) // 2 + c]
            petit = cv2.resize(carre, (cote, cote),
                               interpolation=cv2.INTER_AREA)
            if miroir:
                petit = cv2.flip(petit, 1)
            ok, buf = cv2.imencode('.jpg', petit,
                                   [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ok:
                return ""
            return base64.b64encode(buf.tobytes()).decode('ascii')
        except Exception:
            return ""

    def get_webcams(self) -> dict:
        """Relit les caméras présentes (l'utilisateur vient d'en brancher
        une, ou ouvre les réglages)."""
        try:
            return {'ok': True, 'webcams': self._lister_webcams(rafraichir=True)}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def test_webcam(self, index: int) -> dict:
        """Ouvre la caméra choisie et rend une image, pour lever le doute
        sur l'association nom → index. Bloque au plus 5 s."""
        if self.state != IDLE:
            return {'ok': False,
                    'error': "Webcam occupée par l'enregistrement"}
        source = None
        try:
            source = self._webcam_factory(device_index=int(index))
            source.start()
            fin = time.time() + 5.0
            while time.time() < fin and not source.prete and not source.erreur:
                time.sleep(0.05)
            if source.erreur:
                return {'ok': False, 'error': source.erreur}
            image = source.latest()
            if image is None:
                return {'ok': False,
                        'error': "Aucune image reçue en 5 s"}
            miroir = WebcamOptions.load(self.config)['miroir']
            return {'ok': True,
                    'image': self._vignette_base64(image, 240, miroir)}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        finally:
            if source is not None:
                try:
                    source.stop()
                except Exception:
                    pass
```

Dans `_launch`, après `self._set_state(IDLE)` des deux branches d'échec, appeler `self._fermer_webcam()` ; après `self._start_timer()` ajouter :

```python
        self._annoncer_webcam_absente()
        self._start_webcam_preview()
```

Dans `stop_recording`, branche `PENDING` : `self._fermer_webcam()` avant `self._set_state(IDLE)`.

Dans `_finish`, tout au début du `try` (avant l'arrêt du moteur — la caméra ne sert plus dès que la capture s'arrête) : `self._fermer_webcam()`. Et dans le `finally`, appeler aussi `self._fermer_webcam()` (idempotent) pour couvrir une exception avant la première ligne.

Dans `shutdown`, avant l'arrêt du moteur : `self._fermer_webcam()`.

- [ ] **Step 4 : Vérifier**

Run: `cd LuminaRecorder && python -m pytest tests/test_bridge.py -q`
Expected: tous PASS, anciens compris.

Run: `cd LuminaRecorder && python -m pytest -q --ignore=tests/test_global_hotkey.py`
Expected: vert (338 + les nouveaux).

- [ ] **Step 5 : Commit**

```bash
git add LuminaRecorder/src/webui/bridge.py LuminaRecorder/tests/test_bridge.py
git commit -m "feat: le pont ouvre, ferme et prévisualise la webcam"
```

---

### Task 5 : Vérification réelle et mesure

**Files:**
- Create: `LuminaRecorder/tools/verifier_webcam.py`

Pas de test unitaire : ce script prouve la chaîne complète sur la machine, avec la vraie caméra, sans ouvrir l'interface.

- [ ] **Step 1 : Écrire le script**

```python
"""Preuve sur machine : la webcam s'incruste et coûte ce qu'annoncé.

Usage : python tools/verifier_webcam.py
Ouvre la caméra 0, compose 150 images 1366×768 avec le filtre en
« moyenne », écrit tools/verif_webcam.jpg et affiche le coût moyen.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import cv2
import numpy as np

from core.webcam_source import WebcamSource, lister_webcams
from filters.webcam_overlay_filter import WebcamOverlayFilter


def main():
    cams = lister_webcams()
    print("Caméras :", cams or "aucune")
    if not cams:
        return 1
    source = WebcamSource(device_index=cams[0]['index'])
    t0 = time.perf_counter()
    source.start()
    while not source.prete and not source.erreur and time.perf_counter() - t0 < 8:
        time.sleep(0.05)
    print(f"Ouverture : {time.perf_counter() - t0:.2f} s, erreur : {source.erreur!r}")
    if not source.prete:
        source.stop()
        return 1

    flt = WebcamOverlayFilter(source, forme='rond', coin='bas-droite',
                              taille='moyenne')
    frame = np.full((768, 1366, 3), 40, np.uint8)
    for _ in range(20):
        flt.process(frame.copy())
    t0 = time.perf_counter()
    n = 150
    for _ in range(n):
        sortie = flt.process(frame.copy())
    print(f"Coût moyen : {(time.perf_counter() - t0) / n * 1000:.2f} ms")
    chemin = Path(__file__).parent / 'verif_webcam.jpg'
    cv2.imwrite(str(chemin), sortie)
    print("Image :", chemin)
    source.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2 : Exécuter et regarder l'image**

Run: `cd LuminaRecorder && python tools/verifier_webcam.py`
Expected: ouverture < 4 s, coût < 2 ms, `tools/verif_webcam.jpg` montre le visage rond en bas à droite avec bordure ambre et ombre. **Ouvrir l'image** (outil Read) et vérifier visuellement. Ne pas commiter le `.jpg`.

- [ ] **Step 3 : Commit**

```bash
git add LuminaRecorder/tools/verifier_webcam.py
git commit -m "tools: vérification de l'incrustation webcam sur machine"
```

---

## Auto-revue

- Couverture de la spec : source (T1), filtre avec formes/coins/tailles/miroir/bordure/ombre/dégradation/coût (T2), `[webcam]` et ordre dans la chaîne (T3), pont : réglages, état initial, `get_webcams`, `test_webcam`, ouverture avant décompte, fermeture à l'arrêt/annulation/échec/fermeture, aperçu 8 im/s, avis unique (T4), preuve réelle (T5). Le panneau et le widget sont explicitement reportés au plan capsule.
- Noms cohérents : `WebcamSource.latest/erreur/prete/stop`, `lister_webcams(rafraichir)`, `WebcamOverlayFilter.zone`, `WebcamOptions.load/build_filter`, `build_filters(..., webcam_filter=)`, `bridge._webcam/_webcam_factory/_lister_webcams`, événements `webcam_preview` et `notice`.
