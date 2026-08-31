"""Tests du suivi Smart Focus (core/focus_tracker.py).

La détection Windows elle-même est monkeypatchée : ces tests portent sur
la logique de suivi et de clamping, qui doit être vérifiable sur
n'importe quelle machine.
"""

import pytest

from core import focus_tracker
from core.focus_tracker import FocusTracker, clamp_to_monitor
from core.window_detect import WindowRect


MONITOR = {'left': 0, 'top': 0, 'width': 1366, 'height': 768}


@pytest.fixture
def detection_active(monkeypatch):
    """Rend le Smart Focus 'disponible' sans dépendre de pywin32."""
    monkeypatch.setattr(focus_tracker, 'smart_focus_is_available',
                        lambda: True)


def fake_detection(monkeypatch, *, handle=42, rects=None):
    """Installe une détection factice.

    `rects` : liste de WindowRect (ou None) retournés successivement par
    get_window_rect_by_handle, pour simuler une fenêtre qui bouge.
    """
    sequence = list(rects or [])

    def by_handle(hwnd, with_title=True):
        if not sequence:
            return None
        return sequence.pop(0) if len(sequence) > 1 else sequence[0]

    monkeypatch.setattr(focus_tracker, 'get_foreground_window_handle',
                        lambda: handle)
    monkeypatch.setattr(focus_tracker, 'get_window_rect_by_handle',
                        by_handle)


# --- clamp_to_monitor ---

def test_fenetre_maximisee_est_ramenee_dans_l_ecran():
    """Cas réel : Windows rapporte left=-8 pour une fenêtre maximisée."""
    rect = WindowRect(left=-8, top=-8, width=1382, height=784, title="App")
    region = clamp_to_monitor(rect, MONITOR)

    assert region['left'] == 0
    assert region['top'] == 0
    assert region['left'] + region['width'] <= MONITOR['width']
    assert region['top'] + region['height'] <= MONITOR['height']


def test_dimensions_toujours_paires_pour_h264():
    rect = WindowRect(left=0, top=0, width=801, height=603, title="App")
    region = clamp_to_monitor(rect, MONITOR)

    assert region['width'] % 2 == 0
    assert region['height'] % 2 == 0


def test_fenetre_depassant_a_droite_est_rognee():
    rect = WindowRect(left=1000, top=100, width=800, height=400, title="App")
    region = clamp_to_monitor(rect, MONITOR)

    assert region['left'] == 1000
    assert region['left'] + region['width'] <= MONITOR['width']


def test_dimensions_jamais_nulles():
    """Une fenêtre entièrement hors écran ne doit pas donner 0x0 : mss
    lèverait une exception et l'enregistrement s'arrêterait."""
    rect = WindowRect(left=5000, top=5000, width=300, height=200, title="App")
    region = clamp_to_monitor(rect, MONITOR)

    assert region['width'] >= 2
    assert region['height'] >= 2


def test_fenetre_normale_est_inchangee():
    rect = WindowRect(left=100, top=50, width=800, height=600, title="App")
    region = clamp_to_monitor(rect, MONITOR)

    assert region == {'left': 100, 'top': 50, 'width': 800, 'height': 600}


# --- verrouillage ---

def test_verrouillage_echoue_si_detection_indisponible(monkeypatch):
    monkeypatch.setattr(focus_tracker, 'smart_focus_is_available',
                        lambda: False)
    tracker = FocusTracker(MONITOR)

    assert tracker.lock_on_foreground() is False
    assert tracker.is_locked is False


def test_verrouillage_echoue_sans_fenetre_exploitable(monkeypatch,
                                                      detection_active):
    monkeypatch.setattr(focus_tracker, 'get_foreground_window_handle',
                        lambda: None)
    tracker = FocusTracker(MONITOR)

    assert tracker.lock_on_foreground() is False


def test_verrouillage_memorise_titre_et_taille(monkeypatch, detection_active):
    fake_detection(monkeypatch, rects=[
        WindowRect(left=100, top=50, width=800, height=600, title="Firefox")])
    tracker = FocusTracker(MONITOR)

    assert tracker.lock_on_foreground() is True
    assert tracker.is_locked is True
    assert tracker.window_title == "Firefox"
    assert tracker.current_region() == {'left': 100, 'top': 50,
                                        'width': 800, 'height': 600}


# --- suivi ---

def test_le_deplacement_de_la_fenetre_est_suivi(monkeypatch,
                                                detection_active):
    fake_detection(monkeypatch, rects=[
        WindowRect(left=100, top=50, width=800, height=600, title="App"),
        WindowRect(left=200, top=150, width=800, height=600, title="App"),
    ])
    tracker = FocusTracker(MONITOR)
    tracker.lock_on_foreground()

    region = tracker.current_region()

    assert region['left'] == 200
    assert region['top'] == 150


def test_le_redimensionnement_ne_change_pas_la_resolution(monkeypatch,
                                                          detection_active):
    """cv2.VideoWriter exige une taille fixe : la taille du verrouillage
    doit survivre à un redimensionnement de la fenêtre."""
    fake_detection(monkeypatch, rects=[
        WindowRect(left=100, top=50, width=800, height=600, title="App"),
        WindowRect(left=100, top=50, width=400, height=300, title="App"),
    ])
    tracker = FocusTracker(MONITOR)
    tracker.lock_on_foreground()

    region = tracker.current_region()

    assert region['width'] == 800
    assert region['height'] == 600


def test_fenetre_disparue_garde_la_derniere_zone(monkeypatch,
                                                 detection_active):
    """Fenêtre fermée ou minimisée : on fige plutôt que de sauter."""
    fake_detection(monkeypatch, rects=[
        WindowRect(left=100, top=50, width=800, height=600, title="App"),
        None,
    ])
    tracker = FocusTracker(MONITOR)
    tracker.lock_on_foreground()

    region = tracker.current_region()

    assert region == {'left': 100, 'top': 50, 'width': 800, 'height': 600}


def test_fenetre_sortie_de_l_ecran_est_recalee_sur_le_bord(monkeypatch,
                                                            detection_active):
    """Sortir la fenêtre de l'écran ne doit PAS rogner la zone : la
    résolution est figée. On décale la zone pour qu'elle reste dans
    l'écran, collée au bord."""
    fake_detection(monkeypatch, rects=[
        WindowRect(left=100, top=50, width=800, height=600, title="App"),
        WindowRect(left=1200, top=50, width=800, height=600, title="App"),
    ])
    tracker = FocusTracker(MONITOR)
    tracker.lock_on_foreground()

    region = tracker.current_region()

    assert region['width'] == 800
    assert region['height'] == 600
    # 1366 - 800 = 566 : collée au bord droit, jamais hors écran
    assert region['left'] == 566
    assert region['left'] + region['width'] <= MONITOR['width']


def test_zone_plein_ecran_suit_malgre_le_deplacement(monkeypatch,
                                                     detection_active):
    """Régression : une fenêtre verrouillée maximisée occupe tout l'écran.
    Le suivi doit rester cohérent (zone collée à l'origine) au lieu de se
    figer définitivement sur la première zone."""
    fake_detection(monkeypatch, rects=[
        WindowRect(left=-8, top=-8, width=1382, height=784, title="App"),
        WindowRect(left=50, top=40, width=1382, height=784, title="App"),
    ])
    tracker = FocusTracker(MONITOR)
    tracker.lock_on_foreground()

    region = tracker.current_region()

    # Zone verrouillée = plein écran : aucun décalage possible, elle reste
    # à l'origine plutôt que de sortir de l'écran
    assert region == {'left': 0, 'top': 0, 'width': 1366, 'height': 768}


def test_tracker_non_verrouille_retourne_le_moniteur(monkeypatch,
                                                     detection_active):
    tracker = FocusTracker(MONITOR)

    assert tracker.current_region() == MONITOR


def test_le_suivi_ne_lit_pas_le_titre_a_chaque_frame(monkeypatch,
                                                     detection_active):
    """GetWindowText fait un SendMessage synchrone vers le thread de la
    fenêtre : sur une application figée il bloquerait la boucle de
    capture. Le titre ne doit être lu qu'au verrouillage."""
    appels = []

    def by_handle(hwnd, with_title=True):
        appels.append(with_title)
        return WindowRect(left=100, top=50, width=800, height=600,
                          title="App")

    monkeypatch.setattr(focus_tracker, 'get_foreground_window_handle',
                        lambda: 42)
    monkeypatch.setattr(focus_tracker, 'get_window_rect_by_handle',
                        by_handle)

    tracker = FocusTracker(MONITOR)
    tracker.lock_on_foreground()
    appels.clear()
    tracker.current_region()

    assert appels == [False], "le suivi ne doit pas demander le titre"


def test_moniteur_secondaire_a_coordonnees_negatives():
    """Un écran placé à gauche du principal a un 'left' négatif : le
    clamping doit rester correct dans ce repère."""
    gauche = {'left': -1920, 'top': 0, 'width': 1920, 'height': 1080}
    rect = WindowRect(left=-1930, top=-5, width=800, height=600,
                      title="App")

    region = clamp_to_monitor(rect, gauche)

    assert region['left'] == -1920
    assert region['top'] == 0
    assert region['left'] + region['width'] <= gauche['left'] + gauche['width']


def test_fenetre_plus_grande_que_l_ecran_reste_a_l_origine(monkeypatch,
                                                            detection_active):
    """Fenêtre étalée sur deux écrans alors qu'on ne capture que le
    principal : la zone ne doit pas partir hors des bornes basses."""
    fake_detection(monkeypatch, rects=[
        WindowRect(left=0, top=0, width=2000, height=900, title="App"),
        WindowRect(left=500, top=200, width=2000, height=900, title="App"),
    ])
    tracker = FocusTracker(MONITOR)
    tracker.lock_on_foreground()

    region = tracker.current_region()

    assert region['left'] == MONITOR['left']
    assert region['top'] == MONITOR['top']
