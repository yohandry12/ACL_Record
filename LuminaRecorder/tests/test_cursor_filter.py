"""Tests du filtre curseur : sonde et horloge factices, jamais Win32."""

import os
import time

import numpy as np
import pytest

from filters.cursor_filter import (COULEUR_HALO, DUREE_HALO, FORMES,
                                   CursorFilter, cursor_is_available)


class SondeFactice:
    """État du pointeur piloté par le test."""

    def __init__(self, x=100, y=80, forme='fleche', presse=False):
        self.x = x
        self.y = y
        self.forme_courante = forme
        self.presse = presse
        self.en_panne = False

    def position(self):
        if self.en_panne:
            raise RuntimeError("sonde hors service")
        return self.x, self.y

    def forme(self):
        return self.forme_courante

    def bouton_presse(self):
        return self.presse


def image(h=240, w=320):
    return np.zeros((h, w, 3), dtype=np.uint8)


def region(left=0, top=0, w=320, h=240):
    return {'left': left, 'top': top, 'width': w, 'height': h}


def filtre(sonde, reg=None, halo=True, horloge=None):
    reg = reg if reg is not None else region()
    tics = horloge if horloge is not None else [0.0]
    return CursorFilter(lambda: reg, halo=halo, sonde=sonde,
                        horloge=lambda: tics[0]), tics


def pixels_modifies(avant, apres):
    """Coordonnées (y, x) des pixels qui diffèrent."""
    return np.argwhere(np.any(avant != apres, axis=2))


# --- pointeur ------------------------------------------------------------

@pytest.mark.parametrize('forme', FORMES)
def test_le_pointeur_est_dessine_autour_du_point_chaud(forme):
    sonde = SondeFactice(x=100, y=80, forme=forme)
    f, _ = filtre(sonde)
    avant = image()

    apres = f.process(avant.copy())

    diff = pixels_modifies(avant, apres)
    assert len(diff) > 0
    # Tout ce qui a changé tient dans une fenêtre de 40 px autour du
    # point chaud : le pointeur est bien posé à la position lue
    assert diff[:, 0].min() >= 80 - 20 and diff[:, 0].max() <= 80 + 20
    assert diff[:, 1].min() >= 100 - 20 and diff[:, 1].max() <= 100 + 20
    # Du blanc et du noir : remplissage et contour
    assert (apres == 255).all(axis=2).any()
    assert apres.shape == avant.shape and apres.dtype == avant.dtype


def test_la_forme_inconnue_est_dessinee_comme_une_fleche():
    """Une forme non prévue par la sonde ne doit pas casser le filtre."""
    sonde = SondeFactice(forme='sablier')
    f, _ = filtre(sonde)
    avant = image()
    assert len(pixels_modifies(avant, f.process(avant.copy()))) > 0


def test_le_decalage_de_region_est_applique():
    """Smart Focus : la région commence en (300, 200) sur l'écran, le
    pointeur écran (340, 230) tombe en (40, 30) dans l'image."""
    sonde = SondeFactice(x=340, y=230)
    f, _ = filtre(sonde, reg=region(left=300, top=200))
    avant = image()

    diff = pixels_modifies(avant, f.process(avant.copy()))

    assert diff[:, 0].min() >= 30 - 2 and diff[:, 0].max() <= 30 + 20
    assert diff[:, 1].min() >= 40 - 2 and diff[:, 1].max() <= 40 + 20


def test_les_coordonnees_negatives_de_region_sont_acceptees():
    """Fenêtre maximisée : région à left=-8. Le pointeur écran (2, 50)
    est dans l'image en (10, 50)."""
    sonde = SondeFactice(x=2, y=50)
    f, _ = filtre(sonde, reg=region(left=-8, top=0))
    avant = image()

    diff = pixels_modifies(avant, f.process(avant.copy()))

    assert len(diff) > 0
    assert diff[:, 1].min() >= 10 - 2


def test_pointeur_hors_image_ne_dessine_rien():
    sonde = SondeFactice(x=1000, y=1000)
    f, _ = filtre(sonde)
    avant = image()
    assert np.array_equal(f.process(avant.copy()), avant)


def test_pointeur_masque_ne_dessine_rien():
    sonde = SondeFactice(forme=None)
    f, _ = filtre(sonde)
    avant = image()
    assert np.array_equal(f.process(avant.copy()), avant)


def test_region_absente_rend_l_image_intacte():
    sonde = SondeFactice()
    f = CursorFilter(lambda: None, sonde=sonde, horloge=lambda: 0.0)
    avant = image()
    assert np.array_equal(f.process(avant.copy()), avant)


def test_sonde_en_panne_rend_l_image_intacte():
    """Le filtre ne lève jamais : FilterChain le désactiverait."""
    sonde = SondeFactice()
    sonde.en_panne = True
    f, _ = filtre(sonde)
    avant = image()
    assert np.array_equal(f.process(avant.copy()), avant)


def test_echelle_double_sur_une_image_4k():
    """Le pointeur suit la résolution : deux fois plus haut en 2160p."""
    def hauteur_du_pointeur(h_image):
        sonde = SondeFactice(x=200, y=200)
        f, _ = filtre(sonde, reg=region(w=400, h=h_image))
        avant = image(h=h_image, w=400)
        diff = pixels_modifies(avant, f.process(avant.copy()))
        return diff[:, 0].max() - diff[:, 0].min()

    assert hauteur_du_pointeur(2160) >= 1.8 * hauteur_du_pointeur(1080)


# --- halo ----------------------------------------------------------------

def _pixels_ambres(img):
    """Pixels dont la teinte tire vers l'ambre du halo (R > B)."""
    return int((img[:, :, 2].astype(int) - img[:, :, 0].astype(int) > 60).sum())


def test_un_clic_ouvre_un_halo_ambre():
    sonde = SondeFactice(x=150, y=120, forme=None)   # pointeur masqué : seul le halo compte
    f, tics = filtre(sonde)
    f.process(image())                     # bouton relâché
    sonde.presse = True
    tics[0] = 0.1

    apres = f.process(image())

    assert _pixels_ambres(apres) > 0


def test_bouton_maintenu_ne_produit_qu_un_halo():
    """Front montant : dix images bouton enfoncé = un seul halo."""
    sonde = SondeFactice(forme=None, presse=True)
    f, tics = filtre(sonde)
    for i in range(10):
        tics[0] = i * 0.02
        f.process(image())
    assert len(f._halos) == 1


def test_deux_clics_rapproches_donnent_deux_halos():
    sonde = SondeFactice(forme=None)
    f, tics = filtre(sonde)
    sonde.presse = True; tics[0] = 0.00; f.process(image())
    sonde.presse = False; tics[0] = 0.05; f.process(image())
    sonde.presse = True; tics[0] = 0.10; f.process(image())
    assert len(f._halos) == 2


def test_le_halo_expire_apres_sa_duree():
    sonde = SondeFactice(forme=None, presse=True)
    f, tics = filtre(sonde)
    f.process(image())
    sonde.presse = False
    tics[0] = DUREE_HALO + 0.01

    apres = f.process(image())

    assert f._halos == []
    assert _pixels_ambres(apres) == 0


def test_le_halo_grandit_et_s_estompe():
    sonde = SondeFactice(x=150, y=120, forme=None, presse=True)
    f, tics = filtre(sonde)
    f.process(image())
    sonde.presse = False
    tics[0] = 0.05
    jeune = f.process(image())
    tics[0] = 0.35
    vieux = f.process(image())

    # Plus grand : les pixels touchés s'éloignent du centre
    def rayon_max(img):
        pts = np.argwhere(img[:, :, 2] > 0)
        return np.hypot(pts[:, 0] - 120, pts[:, 1] - 150).max()
    assert rayon_max(vieux) > rayon_max(jeune)
    # Plus pâle : le canal rouge culmine plus bas
    assert vieux[:, :, 2].max() < jeune[:, :, 2].max()


def test_le_halo_reste_a_sa_place_ecran_quand_la_region_bouge():
    """Smart Focus déplace la région entre deux images : le halo reste
    sur le point cliqué de l'écran, pas sur le même pixel de l'image."""
    sonde = SondeFactice(x=200, y=150, forme=None, presse=True)
    reg = region(left=0, top=0)
    tics = [0.0]
    f = CursorFilter(lambda: reg, sonde=sonde, horloge=lambda: tics[0])
    f.process(image())
    sonde.presse = False
    reg['left'] = 50                       # la fenêtre suivie a glissé
    tics[0] = 0.1

    apres = f.process(image())

    pts = np.argwhere(apres[:, :, 2] > 0)
    centre_x = pts[:, 1].mean()
    assert abs(centre_x - 150) < 3         # 200 - 50


def test_halo_au_bord_de_l_image_ne_leve_pas():
    sonde = SondeFactice(x=2, y=2, forme=None, presse=True)
    f, tics = filtre(sonde)
    f.process(image())
    tics[0] = 0.3
    apres = f.process(image())
    assert apres.shape == (240, 320, 3)


def test_halo_desactive_ignore_les_clics():
    sonde = SondeFactice(forme=None, presse=True)
    f, _ = filtre(sonde, halo=False)
    avant = image()
    assert np.array_equal(f.process(avant.copy()), avant)
    assert f._halos == []


# --- performance ---------------------------------------------------------

def test_process_reste_sous_la_milliseconde_en_1080p():
    sonde = SondeFactice(x=960, y=540, presse=True)
    f, tics = filtre(sonde, reg=region(w=1920, h=1080))
    img = image(h=1080, w=1920)
    f.process(img)                          # ouvre un halo
    sonde.presse = False
    debut = time.perf_counter()
    for i in range(100):
        tics[0] = 0.001 * i                # le halo reste actif
        f.process(img)
    moyenne = (time.perf_counter() - debut) / 100
    assert moyenne < 0.001, f"{moyenne * 1000:.2f} ms par image"


# --- disponibilité et sonde réelle ----------------------------------------

def test_disponibilite_suit_le_systeme(monkeypatch):
    monkeypatch.setattr(os, 'name', 'nt', raising=False)
    assert cursor_is_available() is True
    monkeypatch.setattr(os, 'name', 'posix', raising=False)
    assert cursor_is_available() is False


@pytest.mark.skipif(os.name != 'nt', reason="sonde Win32")
def test_la_sonde_reelle_repond_avec_les_bons_types():
    """Seul test qui touche Win32 : types cohérents, pas de valeur."""
    from filters.cursor_filter import SondeWin32
    sonde = SondeWin32()
    x, y = sonde.position()
    assert isinstance(x, int) and isinstance(y, int)
    assert sonde.forme() in FORMES or sonde.forme() is None
    assert isinstance(sonde.bouton_presse(), bool)
