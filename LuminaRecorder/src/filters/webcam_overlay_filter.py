"""
Lumina Filters - Incrustation de la webcam

Compose la dernière image de la caméra dans un coin de chaque image
capturée, découpée selon une forme. Dernier filtre de la chaîne : après
le flou de confidentialité (sinon l'OCR flouterait le visage) et après
les plugins.

Coût maîtrisé : masques calculés une fois par (forme, côté) et mis en
cache ; composition sur la seule zone de la vignette, via cv2.multiply
(plus rapide que la diffusion numpy) et un redimensionnement en
interpolation linéaire. Mesuré autour de 0,5 ms pour une vignette
« moyenne » sur 1366×768, largement sous le budget de 2,5 ms.
"""

from typing import Dict, Tuple

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
        # (forme, cote) -> (masque, masque_inv, ombre_inv), HxWx3 float32
        self._cache: Dict[Tuple[str, int], Tuple[np.ndarray, np.ndarray, np.ndarray]] = {}

    # --- géométrie ---

    def zone(self, frame_h: int, frame_w: int) -> Tuple[int, int, int]:
        """(x, y, côté) de la vignette dans une image de cette taille."""
        cote = int(frame_h * TAILLES[self.taille])
        marge = int(frame_w * MARGE_RATIO)
        x = marge if 'gauche' in self.coin else frame_w - marge - cote
        y = marge if 'haut' in self.coin else frame_h - marge - cote
        return x, y, cote

    # --- masques ---

    def _masques(self, cote: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Masques et compléments, prêts pour cv2.multiply (3 canaux,
        float32) : bien plus rapide que la diffusion numpy sur une image
        BGR (~5x sur la vignette « moyenne »)."""
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
            masque = cv2.cvtColor(forme, cv2.COLOR_GRAY2BGR).astype(np.float32) / 255.0
            masque_inv = 1.0 - masque

            # Ombre : la forme, décalée vers le bas et floutée, sur un
            # canevas assez grand pour le décalage et le flou
            taille_ombre = cote + 2 * OMBRE_RAYON + OMBRE_DECALAGE
            ombre = np.zeros((taille_ombre, taille_ombre), np.uint8)
            ombre[OMBRE_RAYON + OMBRE_DECALAGE:OMBRE_RAYON + OMBRE_DECALAGE + cote,
                  OMBRE_RAYON:OMBRE_RAYON + cote] = forme
            ombre = cv2.GaussianBlur(ombre, (0, 0), OMBRE_RAYON / 2)
            ombre_bgr = cv2.cvtColor(ombre, cv2.COLOR_GRAY2BGR).astype(np.float32) / 255.0 * OMBRE_OPACITE
            ombre_inv = 1.0 - ombre_bgr
            self._cache[cle] = (masque, masque_inv, ombre_inv)
        return self._cache[cle]

    # --- image webcam ---

    def _vignette(self, image: np.ndarray, cote: int) -> np.ndarray:
        """Recadre au carré centré, redimensionne, applique le miroir et
        dessine la bordure dans la forme."""
        h, w = image.shape[:2]
        c = min(h, w)
        y0, x0 = (h - c) // 2, (w - c) // 2
        carre = image[y0:y0 + c, x0:x0 + c]
        # INTER_LINEAR : ~10x plus rapide qu'INTER_AREA pour ce facteur de
        # réduction, sans perte visible sur une vignette de cette taille
        vignette = cv2.resize(carre, (cote, cote), interpolation=cv2.INTER_LINEAR)
        if self.miroir:
            vignette = cv2.flip(vignette, 1)
        if self.forme == 'rond':
            cv2.circle(vignette, (cote // 2, cote // 2), cote // 2 - 1,
                       BORDURE_BGR, BORDURE_PX)
        else:
            # 'carre' et 'carre_arrondi' : contour approché par le
            # rectangle, lisible et bien moins cher qu'un tracé de coins
            # arrondis à chaque image
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
        masque, masque_inv, ombre_inv = self._masques(cote)

        # Ombre, sur une zone un peu plus large que la vignette, bornée
        # à l'image
        ox0, oy0 = x - OMBRE_RAYON, y - OMBRE_RAYON
        ox1, oy1 = ox0 + ombre_inv.shape[1], oy0 + ombre_inv.shape[0]
        sx0, sy0 = max(0, ox0), max(0, oy0)
        sx1, sy1 = min(w, ox1), min(h, oy1)
        if sx1 > sx0 and sy1 > sy0:
            part_inv = ombre_inv[sy0 - oy0:sy1 - oy0, sx0 - ox0:sx1 - ox0]
            zone_ombre = frame[sy0:sy1, sx0:sx1]
            assombri = cv2.multiply(zone_ombre, part_inv, dtype=cv2.CV_8U)
            zone_ombre[:] = assombri

        vignette = self._vignette(image, cote)
        zone = frame[y:y + cote, x:x + cote]
        avant_plan = cv2.multiply(vignette, masque, dtype=cv2.CV_8U)
        arriere_plan = cv2.multiply(zone, masque_inv, dtype=cv2.CV_8U)
        zone[:] = cv2.add(avant_plan, arriere_plan)
        return frame
