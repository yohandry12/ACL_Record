"""
Lumina Recorder - Détection de la fenêtre au premier plan (Windows)

Encapsule les appels win32gui nécessaires au mode "Smart Focus" : savoir
quelle fenêtre est active et où elle se trouve à l'écran, pour pouvoir
cadrer/suivre l'enregistrement dessus.

Nécessite pywin32 (pip install pywin32) : sans lui, la fonctionnalité est
simplement indisponible et le mode Smart Focus reste grisé dans
l'interface — ce module ne doit jamais lever d'exception à l'import, y
compris sur un OS non-Windows où win32gui n'existe de toute façon pas.

Important : les coordonnées retournées sont celles brutes de l'API
Windows. Une fenêtre maximisée déborde fréquemment de quelques pixels à
l'extérieur de l'écran (ex. left=-8) à cause de la bordure invisible de
redimensionnement ; ce module ne corrige PAS ce débordement. Le clamping
aux bornes de l'écran, si nécessaire, est la responsabilité de
l'appelant.
"""

import ctypes
import os
from dataclasses import dataclass
from typing import Optional

try:
    import win32gui
except ImportError:  # pragma: no cover - dépend de l'environnement
    win32gui = None


def enable_dpi_awareness() -> bool:
    """Déclare le processus « DPI-aware » auprès de Windows.

    INDISPENSABLE au Smart Focus. Par défaut, un processus Python/Tkinter
    est DPI-unaware : sur un écran mis à l'échelle (125 %, 150 %, 200 % —
    le cas de la plupart des portables récents), Windows lui ment et
    renvoie des coordonnées virtualisées en 96 DPI. GetWindowRect
    retournerait alors des valeurs à l'échelle logique tandis que mss
    capture en pixels physiques : la zone enregistrée serait décalée et
    mal dimensionnée, proportionnellement au facteur d'échelle.

    À appeler une seule fois, avant toute création de fenêtre (Windows
    refuse le changement ensuite). Sans effet sur un écran à 100 %, ce qui
    explique qu'un test sur une telle machine ne révèle pas le problème.

    Returns:
        True si le processus est désormais DPI-aware.
    """
    if os.name != 'nt':
        return False
    try:
        # Per-Monitor v2 (Windows 10 1703+) : gère aussi le cas de deux
        # écrans à des échelles différentes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4))
        return True
    except Exception:
        pass
    try:
        # Repli Windows 8.1 : 2 = PROCESS_PER_MONITOR_DPI_AWARE
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except Exception:
        pass
    try:
        # Repli Windows 7 : échelle système uniquement
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


# Titres de fenêtres "shell" qui ne représentent pas une vraie application
# et qui peuvent parfois passer au premier plan (bureau, recherche Windows,
# petit widget de saisie tactile...).
_SHELL_WINDOW_TITLES = {"Program Manager", "Windows Input Experience", "Search"}

# Une fenêtre plus petite que ceci n'est pas exploitable pour un
# enregistrement (typiquement une infobulle ou un petit widget système).
_MIN_USEFUL_SIZE = 100


@dataclass
class WindowRect:
    """Rectangle et titre d'une fenêtre, tels que rapportés par Windows.

    Les coordonnées (left, top) peuvent être négatives : voir la
    docstring du module pour le cas des fenêtres maximisées.
    """
    left: int
    top: int
    width: int
    height: int
    title: str


def window_detection_is_available() -> bool:
    """True si la détection de fenêtre est possible sur cette machine.

    Nécessite à la fois pywin32 installé ET un OS Windows (win32gui peut
    théoriquement être importable sans être fonctionnel ailleurs, on
    vérifie donc aussi os.name).
    """
    return win32gui is not None and os.name == 'nt'


def _is_rejected_window(hwnd: int, rect: WindowRect,
                        check_title: bool = True) -> bool:
    """Applique les filtres de rejet communs à une fenêtre candidate.

    `check_title` est False quand le titre n'a pas été lu (voir
    get_window_rect_by_handle) : le filtre sur le titre est alors sauté,
    la fenêtre ayant de toute façon déjà été validée au verrouillage.
    """
    # Fenêtre non visible (masquée, détruite, appartenant à un autre bureau...)
    if not win32gui.IsWindowVisible(hwnd):
        return True

    # Fenêtre minimisée : rien à afficher/enregistrer
    if win32gui.IsIconic(hwnd):
        return True

    # Dimensions invalides ou nulles
    if rect.width <= 0 or rect.height <= 0:
        return True

    # Trop petite pour un enregistrement utile
    if rect.width < _MIN_USEFUL_SIZE or rect.height < _MIN_USEFUL_SIZE:
        return True

    # Bureau / shell : titre vide ou classe shell connue
    if check_title and (not rect.title
                        or rect.title in _SHELL_WINDOW_TITLES):
        return True

    return False


def get_window_rect_by_handle(hwnd: int,
                              with_title: bool = True) -> Optional[WindowRect]:
    """Retourne le WindowRect du handle donné, ou None si indisponible/rejeté.

    Ne lève jamais d'exception : toute erreur win32gui (fenêtre détruite
    entre-temps, handle invalide...) est attrapée et donne None.

    Args:
        with_title: si False, saute GetWindowText et le filtre sur le
            titre. GetWindowText fait un SendMessage synchrone vers le
            thread propriétaire de la fenêtre : sur une application qui ne
            répond plus, l'appel peut bloquer plusieurs secondes. Le
            suivi image par image n'a pas besoin du titre — il le lit une
            seule fois au verrouillage — et ne doit pas risquer de geler
            la boucle de capture.
    """
    if win32gui is None or not hwnd:
        return None

    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        title = win32gui.GetWindowText(hwnd) if with_title else ""

        rect = WindowRect(
            left=left,
            top=top,
            width=right - left,
            height=bottom - top,
            title=title,
        )

        if _is_rejected_window(hwnd, rect, check_title=with_title):
            return None

        return rect
    except Exception:
        # Cas réel et fréquent : la fenêtre a été fermée/détruite entre
        # deux appels. Une détection qui échoue doit dégrader proprement,
        # jamais casser l'enregistrement.
        return None


def get_foreground_window_handle() -> Optional[int]:
    """Retourne le hwnd de la fenêtre au premier plan, ou None.

    Retourne None si la détection est indisponible, si le hwnd est
    falsy (0), ou si la fenêtre est rejetée par les filtres de
    get_window_rect_by_handle (minimisée, trop petite, shell...).
    """
    if win32gui is None:
        return None

    try:
        hwnd = win32gui.GetForegroundWindow()
    except Exception:
        return None

    if not hwnd:
        return None

    if get_window_rect_by_handle(hwnd) is None:
        return None

    return hwnd


def get_foreground_window_rect() -> Optional[WindowRect]:
    """Retourne le WindowRect de la fenêtre au premier plan, ou None."""
    if win32gui is None:
        return None

    try:
        hwnd = win32gui.GetForegroundWindow()
    except Exception:
        return None

    if not hwnd:
        return None

    return get_window_rect_by_handle(hwnd)
