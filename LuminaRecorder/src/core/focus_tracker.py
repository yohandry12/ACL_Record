"""
Lumina Recorder - Smart Focus : suivi de la fenêtre active

Verrouille l'enregistrement sur la fenêtre au premier plan au moment du
démarrage, puis suit ses déplacements pendant la capture.

Pourquoi verrouiller la TAILLE au démarrage
-------------------------------------------
cv2.VideoWriter exige une résolution fixe pour toute la durée du fichier.
Redimensionner la zone capturée en cours de route produirait soit un
fichier corrompu, soit des frames rejetées. On fige donc la taille à la
première mesure ; seule la POSITION suit la fenêtre. Si l'utilisateur
redimensionne la fenêtre pendant l'enregistrement, on continue de capturer
un rectangle de la taille d'origine ancré sur son coin haut-gauche.

Pourquoi rester sur la fenêtre d'origine
----------------------------------------
Suivre le premier plan à chaque instant ferait sauter la capture vers
l'explorateur de fichiers, une notification ou Lumina lui-même dès que
l'utilisateur clique ailleurs. On mémorise le handle au démarrage et on
ne suit que celui-là. Si cette fenêtre disparaît (fermée, minimisée), on
garde la dernière position connue plutôt que de sauter ailleurs.

Le clamping aux bornes de l'écran est fait ici : window_detect retourne
les coordonnées brutes de Windows, où une fenêtre maximisée déborde
typiquement de 8 px de chaque côté (bordure invisible de
redimensionnement). Sans clamping, mss capturerait hors écran.
"""

from typing import Optional

from .window_detect import (WindowRect, get_foreground_window_handle,
                            get_window_rect_by_handle,
                            window_detection_is_available)


def smart_focus_is_available() -> bool:
    """True si le Smart Focus est utilisable (pywin32 + Windows)."""
    return window_detection_is_available()


def clamp_to_monitor(rect: WindowRect, monitor: dict) -> dict:
    """Ramène `rect` dans les bornes de `monitor`, au format mss.

    `monitor` est un dict mss : {'left', 'top', 'width', 'height'}.
    Retourne un dict du même format, garanti à l'intérieur de l'écran et
    de dimensions strictement positives.

    Les dimensions sont forcées à un multiple de 2 : les encodeurs H.264
    (libx264 via FFmpeg, étape finale de Lumina) refusent les largeurs ou
    hauteurs impaires.
    """
    mon_left = monitor['left']
    mon_top = monitor['top']
    mon_right = mon_left + monitor['width']
    mon_bottom = mon_top + monitor['height']

    left = max(mon_left, min(rect.left, mon_right - 1))
    top = max(mon_top, min(rect.top, mon_bottom - 1))
    right = min(mon_right, rect.left + rect.width)
    bottom = min(mon_bottom, rect.top + rect.height)

    width = max(2, right - left)
    height = max(2, bottom - top)

    # Dimensions paires pour l'encodeur H.264
    width -= width % 2
    height -= height % 2

    return {'left': left, 'top': top, 'width': width, 'height': height}


class FocusTracker:
    """Suit la fenêtre choisie au démarrage et fournit la zone à capturer.

    Cycle de vie :
        tracker = FocusTracker(monitor)
        if not tracker.lock_on_foreground():   # au démarrage
            ...  # aucune fenêtre exploitable, on reste plein écran
        region = tracker.current_region()      # à chaque frame
    """

    def __init__(self, monitor: dict):
        """
        Args:
            monitor: dict mss du moniteur, sert de bornes au clamping et
                     de zone de repli si aucune fenêtre n'est détectée.
        """
        self.monitor = monitor
        self.hwnd: Optional[int] = None
        self.window_title = ""
        # Taille figée au verrouillage : la sortie vidéo ne peut pas
        # changer de résolution en cours de route
        self._locked_width = 0
        self._locked_height = 0
        # Dernière zone valide : conservée si la fenêtre disparaît
        self._last_region: Optional[dict] = None

    @property
    def is_locked(self) -> bool:
        """True si une fenêtre est effectivement suivie."""
        return self.hwnd is not None

    def lock_on_foreground(self) -> bool:
        """Verrouille le suivi sur la fenêtre actuellement au premier plan.

        Returns:
            True si une fenêtre exploitable a été trouvée. False sinon —
            l'appelant doit alors enregistrer l'écran entier.
        """
        if not smart_focus_is_available():
            return False

        hwnd = get_foreground_window_handle()
        if hwnd is None:
            return False

        rect = get_window_rect_by_handle(hwnd)
        if rect is None:
            return False

        region = clamp_to_monitor(rect, self.monitor)

        self.hwnd = hwnd
        self.window_title = rect.title
        self._locked_width = region['width']
        self._locked_height = region['height']
        self._last_region = region
        return True

    def current_region(self) -> dict:
        """Zone à capturer maintenant, au format mss.

        Suit la position de la fenêtre verrouillée en conservant la taille
        figée au démarrage. Si la fenêtre n'est plus lisible (fermée,
        minimisée, déplacée sur un autre bureau), retourne la dernière
        zone connue : mieux vaut une image figée qu'un saut brutal ou un
        plantage.
        """
        if not self.is_locked:
            return self._last_region or dict(self.monitor)

        # with_title=False : ce chemin tourne à chaque frame (30 fois par
        # seconde) et GetWindowText peut bloquer sur une application qui
        # ne répond plus. Le titre n'est lu qu'au verrouillage.
        rect = get_window_rect_by_handle(self.hwnd, with_title=False)
        if rect is None:
            return self._last_region or dict(self.monitor)

        # Seule la position suit ; la taille reste celle du verrouillage.
        # On décale la position pour que la zone (de taille figée) tienne
        # dans l'écran, au lieu de la rogner : rogner changerait la
        # résolution, que cv2.VideoWriter n'accepte pas. Une fenêtre à
        # moitié sortie de l'écran donne donc une zone collée au bord —
        # c'est le comportement voulu, on filme toujours la même surface.
        max_left = self.monitor['left'] + self.monitor['width'] - self._locked_width
        max_top = self.monitor['top'] + self.monitor['height'] - self._locked_height
        left = max(self.monitor['left'], min(rect.left, max_left))
        top = max(self.monitor['top'], min(rect.top, max_top))

        region = {'left': left, 'top': top,
                  'width': self._locked_width,
                  'height': self._locked_height}
        self._last_region = region
        return region
