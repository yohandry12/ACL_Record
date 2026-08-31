"""Tests de la détection de la fenêtre au premier plan (win32gui)."""

import os

import pytest

from core import window_detect
from core.window_detect import (WindowRect, window_detection_is_available,
                                 get_foreground_window_rect,
                                 get_window_rect_by_handle,
                                 get_foreground_window_handle)


class FakeWin32Gui:
    """Simule win32gui : un hwnd de premier plan et une table de fenêtres."""

    def __init__(self):
        self.foreground_hwnd = 42
        # hwnd -> (left, top, right, bottom, title, visible, iconic)
        self.windows = {}
        self.raise_on = set()  # noms de méthodes à faire exploser

    def add_window(self, hwnd, left, top, right, bottom, title,
                    visible=True, iconic=False):
        self.windows[hwnd] = (left, top, right, bottom, title, visible, iconic)

    def _maybe_raise(self, name):
        if name in self.raise_on:
            raise RuntimeError(f"{name} a échoué (fenêtre détruite)")

    def GetForegroundWindow(self):
        self._maybe_raise('GetForegroundWindow')
        return self.foreground_hwnd

    def GetWindowRect(self, hwnd):
        self._maybe_raise('GetWindowRect')
        left, top, right, bottom, _, _, _ = self.windows[hwnd]
        return (left, top, right, bottom)

    def GetWindowText(self, hwnd):
        self._maybe_raise('GetWindowText')
        return self.windows[hwnd][4]

    def IsWindowVisible(self, hwnd):
        self._maybe_raise('IsWindowVisible')
        return self.windows[hwnd][5]

    def IsIconic(self, hwnd):
        self._maybe_raise('IsIconic')
        return self.windows[hwnd][6]


@pytest.fixture
def fake(monkeypatch):
    f = FakeWin32Gui()
    monkeypatch.setattr(window_detect, 'win32gui', f)
    monkeypatch.setattr(os, 'name', 'nt', raising=False)
    return f


# --- window_detection_is_available -----------------------------------

def test_unavailable_without_win32gui(monkeypatch):
    monkeypatch.setattr(window_detect, 'win32gui', None)
    assert window_detection_is_available() is False


def test_available_with_win32gui_on_windows(fake, monkeypatch):
    monkeypatch.setattr(os, 'name', 'nt', raising=False)
    assert window_detection_is_available() is True


def test_unavailable_on_non_windows_even_with_win32gui(fake, monkeypatch):
    monkeypatch.setattr(os, 'name', 'posix', raising=False)
    assert window_detection_is_available() is False


# --- rect nominal -------------------------------------------------------

def test_nominal_rect_converted_correctly(fake):
    fake.add_window(42, 100, 200, 500, 800, "Bloc-notes")
    rect = get_window_rect_by_handle(42)
    assert rect == WindowRect(left=100, top=200, width=400, height=600,
                               title="Bloc-notes")


def test_foreground_window_rect_matches_handle(fake):
    fake.add_window(42, 0, 0, 1920, 1080, "Navigateur")
    rect = get_foreground_window_rect()
    assert rect.width == 1920
    assert rect.height == 1080
    assert rect.title == "Navigateur"


def test_foreground_window_handle_returned(fake):
    fake.add_window(42, 0, 0, 1920, 1080, "Navigateur")
    assert get_foreground_window_handle() == 42


# --- filtres de rejet -----------------------------------------------------

def test_minimized_window_rejected(fake):
    fake.add_window(42, 0, 0, 800, 600, "App minimisée", iconic=True)
    assert get_window_rect_by_handle(42) is None


def test_invisible_window_rejected(fake):
    fake.add_window(42, 0, 0, 800, 600, "App cachée", visible=False)
    assert get_window_rect_by_handle(42) is None


def test_too_small_window_rejected(fake):
    fake.add_window(42, 0, 0, 50, 50, "Tooltip")
    assert get_window_rect_by_handle(42) is None


def test_zero_or_negative_size_rejected(fake):
    fake.add_window(42, 100, 100, 100, 100, "Fenêtre vide")
    assert get_window_rect_by_handle(42) is None


def test_program_manager_rejected(fake):
    fake.add_window(42, 0, 0, 1920, 1080, "Program Manager")
    assert get_window_rect_by_handle(42) is None


def test_empty_title_rejected(fake):
    fake.add_window(42, 0, 0, 1920, 1080, "")
    assert get_window_rect_by_handle(42) is None


def test_other_shell_titles_rejected(fake):
    fake.add_window(42, 0, 0, 1920, 1080, "Windows Input Experience")
    assert get_window_rect_by_handle(42) is None
    fake.windows[42] = (0, 0, 1920, 1080, "Search", True, False)
    assert get_window_rect_by_handle(42) is None


def test_foreground_handle_none_when_rejected(fake):
    fake.add_window(42, 0, 0, 800, 600, "App minimisée", iconic=True)
    assert get_foreground_window_handle() is None


# --- exceptions win32gui -> dégradation propre --------------------------

def test_exception_on_get_window_rect_returns_none(fake):
    fake.add_window(42, 0, 0, 800, 600, "App")
    fake.raise_on.add('GetWindowRect')
    assert get_window_rect_by_handle(42) is None


def test_exception_on_get_foreground_window_returns_none(fake):
    fake.raise_on.add('GetForegroundWindow')
    assert get_foreground_window_rect() is None
    assert get_foreground_window_handle() is None


def test_exception_on_is_window_visible_returns_none(fake):
    fake.add_window(42, 0, 0, 800, 600, "App")
    fake.raise_on.add('IsWindowVisible')
    assert get_window_rect_by_handle(42) is None


# --- hwnd falsy / indisponible ------------------------------------------

def test_get_window_rect_by_handle_falsy_hwnd(fake):
    assert get_window_rect_by_handle(0) is None
    assert get_window_rect_by_handle(None) is None


def test_get_foreground_window_handle_falsy(fake):
    fake.foreground_hwnd = 0
    assert get_foreground_window_handle() is None


def test_all_functions_none_without_win32gui(monkeypatch):
    monkeypatch.setattr(window_detect, 'win32gui', None)
    assert get_foreground_window_rect() is None
    assert get_window_rect_by_handle(1) is None
    assert get_foreground_window_handle() is None


# --- coordonnées négatives (fenêtre maximisée) ---------------------------

def test_negative_coordinates_preserved_as_is(fake):
    """Une fenêtre maximisée peut déborder légèrement de l'écran (ex.
    left=-8) : ces valeurs brutes ne doivent PAS être corrigées ici."""
    fake.add_window(42, -8, -8, 1928, 1088, "App maximisée")
    rect = get_window_rect_by_handle(42)
    assert rect.left == -8
    assert rect.top == -8
    assert rect.width == 1936
    assert rect.height == 1096


# --- test d'intégration optionnel (réelle machine Windows) --------------

@pytest.mark.skipif(not window_detection_is_available(),
                     reason="nécessite pywin32 et Windows")
def test_integration_real_foreground_window():
    """Test d'intégration : interroge la vraie fenêtre au premier plan.

    Ne vérifie pas de valeur précise (dépend de la machine), seulement
    que l'appel ne lève pas et retourne un type cohérent.
    """
    rect = get_foreground_window_rect()
    assert rect is None or isinstance(rect, WindowRect)
