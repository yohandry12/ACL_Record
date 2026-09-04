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
