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
