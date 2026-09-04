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
