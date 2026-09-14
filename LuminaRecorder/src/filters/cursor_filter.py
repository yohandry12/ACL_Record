"""
Lumina Recorder - Curseur et halo de clic

mss ne capture pas le pointeur de la souris : sans ce filtre, une vidéo
Lumina n'a aucun pointeur, ce qui rend un tutoriel difficile à suivre.

Le pointeur est dessiné en vectoriel (cv2) à la position lue par Win32,
sous deux formes (flèche, barre de texte) choisies d'après le curseur
système courant. Un halo ambre s'ouvre à chaque clic.

Pourquoi ctypes et le sondage plutôt qu'un hook souris
-------------------------------------------------------
Un hook WH_MOUSE_LL intercepte toute la souris du système : suspect pour
un antivirus, et fragile (Windows le retire s'il répond trop lentement).
On lit GetAsyncKeyState à chaque image. Le bit 0x8000 (« enfoncé
maintenant ») ne suffit pas : la capture réelle tourne autour de 15
images par seconde, soit un sondage toutes les 65 ms, et un clic de
50 à 80 ms passait entre deux sondages — constaté sur un enregistrement
où un clic sur deux n'avait pas de halo. On lit donc aussi le bit
0x0001 (« pressé depuis le dernier appel »), qui retient un clic même
bref. Réserve : un autre processus qui interroge le même bouton peut
consommer ce bit ; en pratique rare, et le bit 0x8000 reste en secours.

Les coordonnées de GetCursorPos sont physiques parce que le processus
est déclaré DPI-aware (window_detect.enable_dpi_awareness) : ce sont
les mêmes pixels que la région mss.

Pourquoi le vectoriel et pas la bitmap Windows
----------------------------------------------
DrawIconEx dans un DC puis conversion en numpy coûte plus que le budget
d'une image et dépend du thème. Deux formes dessinées suffisent à
suivre un tutoriel : flèche, et barre de texte dans un champ. Toute
autre forme (main sur un lien, attente, redimensionnement) est une
flèche : une main stylisée en quelques pixels ressemblait à un bloc
blanc, la flèche est lisible partout.
"""

import ctypes
import os
import time
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from .base import FrameFilter

# Ambre de la vignette webcam, en BGR
COULEUR_HALO = (11, 158, 245)
DUREE_HALO = 0.4               # secondes
RAYON_HALO_DEBUT = 8           # px à l'échelle 1
RAYON_HALO_FIN = 28
EPAISSEUR_HALO = 3
OPACITE_HALO = 0.9
HAUTEUR_POINTEUR = 19          # px : flèche Windows à 100 %

FORMES = ('fleche', 'texte')

# GetAsyncKeyState : bit « enfoncé maintenant » et bit « pressé depuis
# le dernier appel ». Le second retient un clic plus court qu'un sondage.
_BOUTON_ENFONCE = 0x8000
_BOUTON_PRESSE_DEPUIS = 0x0001

BLANC = (255, 255, 255)
NOIR = (0, 0, 0)


def cursor_is_available() -> bool:
    """True si le pointeur peut être lu : Windows uniquement."""
    return os.name == 'nt'


# --- sonde Win32 -----------------------------------------------------------

class _POINT(ctypes.Structure):
    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]


class _CURSORINFO(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.c_uint32),
                ('flags', ctypes.c_uint32),
                ('hCursor', ctypes.c_void_p),
                ('ptScreenPos', _POINT)]


class SondeWin32:
    """Lit l'état du pointeur par ctypes (user32). Windows uniquement.

    Les handles des curseurs standard sont chargés une fois : comparer
    `hCursor` à ces handles est immédiat, alors que lire la bitmap ne
    tiendrait pas dans le budget d'une image.
    """

    VK_LBUTTON = 0x01
    VK_RBUTTON = 0x02
    CURSOR_SHOWING = 0x00000001
    IDC_IBEAM = 32513

    def __init__(self):
        u = ctypes.windll.user32
        u.GetCursorPos.argtypes = [ctypes.c_void_p]
        u.GetCursorPos.restype = ctypes.c_int
        u.GetCursorInfo.argtypes = [ctypes.c_void_p]
        u.GetCursorInfo.restype = ctypes.c_int
        # Sans restype explicite, ctypes tronque le handle à 32 bits
        u.LoadCursorW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        u.LoadCursorW.restype = ctypes.c_void_p
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetAsyncKeyState.restype = ctypes.c_short
        self._u = u
        self._formes = {
            u.LoadCursorW(None, self.IDC_IBEAM): 'texte',
        }

    def position(self) -> Tuple[int, int]:
        pt = _POINT()
        if not self._u.GetCursorPos(ctypes.byref(pt)):
            raise OSError("GetCursorPos a échoué")
        return int(pt.x), int(pt.y)

    def forme(self) -> Optional[str]:
        info = _CURSORINFO()
        info.cbSize = ctypes.sizeof(_CURSORINFO)
        if not self._u.GetCursorInfo(ctypes.byref(info)):
            raise OSError("GetCursorInfo a échoué")
        if not info.flags & self.CURSOR_SHOWING:
            return None
        return self._formes.get(info.hCursor, 'fleche')

    def bouton_presse(self) -> bool:
        etat = (self._u.GetAsyncKeyState(self.VK_LBUTTON)
                | self._u.GetAsyncKeyState(self.VK_RBUTTON))
        return bool(etat & (_BOUTON_ENFONCE | _BOUTON_PRESSE_DEPUIS))


# --- dessin ------------------------------------------------------------------

# Contour de la flèche Windows, pointe en (0, 0), pour 19 px de haut
_FLECHE = np.array([(0, 0), (0, 16), (4, 12), (7, 19), (10, 18),
                    (7, 11), (12, 11)], dtype=np.float32)


def _dessiner_pointeur(frame: np.ndarray, x: int, y: int, forme: str,
                       echelle: float) -> None:
    """Dessine le pointeur, point chaud en (x, y), en place."""
    if forme == 'texte':
        demi = int(9 * echelle)
        serif = max(2, int(3 * echelle))
        segments = [((x, y - demi), (x, y + demi)),
                    ((x - serif, y - demi), (x + serif, y - demi)),
                    ((x - serif, y + demi), (x + serif, y + demi))]
        for a, b in segments:
            cv2.line(frame, a, b, NOIR, 3, cv2.LINE_AA)
        for a, b in segments:
            # LINE_8 (pas LINE_AA) : le trait blanc garde un cœur à 255,
            # l'anticrénelage du contour noir en dessous suffit au rendu
            cv2.line(frame, a, b, BLANC, 1, cv2.LINE_8)
        return

    # 'fleche' et toute forme inconnue
    pts = (_FLECHE * (HAUTEUR_POINTEUR * echelle / 19.0)
           + np.array((x, y), dtype=np.float32)).astype(np.int32)
    cv2.fillPoly(frame, [pts], BLANC, cv2.LINE_AA)
    cv2.polylines(frame, [pts], True, NOIR, 1, cv2.LINE_AA)


def _dessiner_halo(frame: np.ndarray, x: int, y: int, age: float,
                   echelle: float) -> None:
    """Anneau qui grandit et s'estompe, composé sur la seule ROI utile."""
    t = min(1.0, max(0.0, age / DUREE_HALO))
    rayon = int((RAYON_HALO_DEBUT
                 + (RAYON_HALO_FIN - RAYON_HALO_DEBUT) * t) * echelle)
    alpha = OPACITE_HALO * (1.0 - t)
    epaisseur = max(1, int(EPAISSEUR_HALO * echelle))
    marge = rayon + epaisseur + 1

    h, w = frame.shape[:2]
    x0, y0 = max(0, x - marge), max(0, y - marge)
    x1, y1 = min(w, x + marge), min(h, y + marge)
    if x1 <= x0 or y1 <= y0:
        return

    roi = frame[y0:y1, x0:x1]
    calque = roi.copy()
    cv2.circle(calque, (x - x0, y - y0), rayon, COULEUR_HALO, epaisseur,
               cv2.LINE_AA)
    cv2.addWeighted(calque, alpha, roi, 1.0 - alpha, 0.0, dst=roi)


# --- filtre ------------------------------------------------------------------

class CursorFilter(FrameFilter):
    """Dessine le pointeur et le halo de clic sur chaque image.

    `region_provider` rend la région mss (left, top, width, height) de
    l'image en cours : le pointeur est en coordonnées écran, l'image en
    coordonnées de région. `None` = image rendue telle quelle.

    Les halos sont mémorisés en coordonnées écran : si Smart Focus
    déplace la région entre deux images, le halo reste sur le point
    cliqué et non sur le même pixel de l'image.
    """

    name = "cursor"

    def __init__(self, region_provider: Callable[[], Optional[dict]],
                 halo: bool = True, sonde=None,
                 horloge: Callable[[], float] = time.monotonic):
        super().__init__()
        self._region = region_provider
        self._halo = halo
        self._sonde = sonde if sonde is not None else SondeWin32()
        self._horloge = horloge
        self._bouton_avant = False
        # (instant du clic, x écran, y écran)
        self._halos: List[Tuple[float, int, int]] = []

    def process(self, frame: np.ndarray) -> np.ndarray:
        try:
            region = self._region()
            if not region:
                return frame
            x, y = self._sonde.position()
            forme = self._sonde.forme()
            presse = self._sonde.bouton_presse() if self._halo else False
            # Une sonde qui échoue ne doit pas faire désactiver le filtre par
            # FilterChain : l'image passe sans pointeur. Le dessin est couvert aussi.

            maintenant = self._horloge()
            if self._halo:
                if presse and not self._bouton_avant:
                    self._halos.append((maintenant, x, y))
                self._bouton_avant = presse
                self._halos = [h for h in self._halos
                               if maintenant - h[0] < DUREE_HALO]

            left, top = int(region['left']), int(region['top'])
            h, w = frame.shape[:2]
            echelle = min(2.0, max(1.0, h / 1080.0))

            for t_clic, hx, hy in self._halos:
                _dessiner_halo(frame, hx - left, hy - top, maintenant - t_clic,
                               echelle)

            fx, fy = x - left, y - top
            if forme is not None and 0 <= fx < w and 0 <= fy < h:
                _dessiner_pointeur(frame, fx, fy, forme, echelle)
        except Exception:
            # Une région malformée ou un appel système défaillant ne lève jamais
            pass
        return frame
