"""Tests de l'incrustation webcam, sur images synthétiques."""

import time

import numpy as np
import pytest

from filters.webcam_overlay_filter import (COINS, FORMES, OMBRE_DECALAGE,
                                           OMBRE_OPACITE, OMBRE_RAYON,
                                           TAILLES, WebcamOverlayFilter)


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


@pytest.mark.parametrize('coin', COINS)
def test_une_image_trop_etroite_est_rendue_telle_quelle(coin):
    """Image très allongée (1000×200) : le côté calculé sur la hauteur
    dépasse la largeur, donc la vignette ne tient dans aucun coin. La
    découpe serait plus petite que le masque et cv2.multiply lèverait :
    on doit rendre l'image inchangée, sans exception, sinon la chaîne
    désactiverait le filtre avec un avis « trop lent » trompeur."""
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()), coin=coin,
                              taille='grande')
    frame = ecran(1000, 200)
    assert flt.process(frame) is frame
    assert not frame.any()          # rien n'a été dessiné


def test_une_image_minuscule_est_rendue_telle_quelle():
    """20×20 : côté de 6 px, sous le minimum de 8 — rien à incruster."""
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()), taille='grande')
    frame = ecran(20, 20)
    assert flt.process(frame) is frame
    assert not frame.any()


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


@pytest.mark.parametrize('forme', FORMES)
def test_les_masques_sont_complementaires(forme):
    """masque + masque_inv == 1 partout, et l'ombre reste dans les bornes
    d'opacité attendues : ça garantit que _masques() produit un vrai
    mélange alpha (pas une coupure nette), indépendamment de la forme."""
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()), forme=forme)
    masque, masque_inv, ombre_inv = flt._masques(168)
    assert masque.dtype == np.float32
    assert np.allclose(masque + masque_inv, 1.0)
    assert np.all(ombre_inv >= 1.0 - OMBRE_OPACITE)
    assert np.all(ombre_inv <= 1.0)


def test_le_melange_est_progressif_sur_l_ombre():
    """L'ombre est un flou gaussien : sous la vignette, l'assombrissement
    doit décroître progressivement (plusieurs valeurs distinctes, jamais
    plus sombre en s'éloignant) plutôt que s'arrêter net."""
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()), forme='carre',
                              coin='haut-gauche')
    frame = np.full((768, 1366, 3), 255, np.uint8)
    x, y, cote = flt.zone(*frame.shape[:2])
    sortie = flt.process(frame)

    colonne = x + cote // 2
    lignes = range(y + cote + 1, y + cote + OMBRE_RAYON + OMBRE_DECALAGE + 1)
    valeurs = [int(sortie[ligne, colonne, 0]) for ligne in lignes]
    assert valeurs[0] < 255, "l'ombre doit assombrir juste sous la vignette"
    assert all(a <= b for a, b in zip(valeurs, valeurs[1:])), \
        "l'assombrissement doit décroître en s'éloignant, jamais l'inverse"
    assert len(set(valeurs)) >= 2, "un vrai fondu a plusieurs paliers"


def test_le_rond_a_un_bord_anticrenele():
    """Sur le pourtour du rond, un pixel à alpha partiel (ni fond pur, ni
    vignette pure) prouve que le contour est mélangé, pas juste coupé net
    au pixel près."""
    flt = WebcamOverlayFilter(SourceFixe(image_webcam()), forme='rond',
                              coin='haut-gauche', taille='moyenne')
    frame = ecran()
    x, y, cote = flt.zone(*frame.shape[:2])
    masque, _, _ = flt._masques(cote)

    ligne_mediane = cote // 2
    valeurs_alpha = masque[ligne_mediane, :, 0]
    idx = next((i for i, v in enumerate(valeurs_alpha) if 0.05 < v < 0.95),
               None)
    assert idx is not None, "le rond devrait avoir un bord anticrénelé"

    sortie = flt.process(frame)
    pixel = tuple(int(v) for v in sortie[y + ligne_mediane, x + idx])
    assert pixel != (0, 0, 0), "pas le fond pur"
    vignette = flt._vignette(image_webcam(), cote)
    pixel_vignette = tuple(int(v) for v in vignette[ligne_mediane, idx])
    assert pixel != pixel_vignette, "pas la vignette pure : un vrai mélange"
