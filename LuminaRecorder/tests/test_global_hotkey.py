"""Tests du raccourci clavier global (core/global_hotkey.py).

L'analyse des libellés est testable partout ; l'enregistrement auprès de
Windows ne l'est que sous Windows et est marqué en conséquence.
"""

import os

import pytest

from core.global_hotkey import (DEFAULT_HOTKEY, MOD_ALT, MOD_CONTROL,
                                MOD_NOREPEAT, MOD_SHIFT, MOD_WIN, VK_F1,
                                GlobalHotkey, hotkey_is_available,
                                parse_hotkey)


windows_seulement = pytest.mark.skipif(
    os.name != 'nt', reason="RegisterHotKey n'existe que sous Windows")


# --- analyse des libellés ---

def test_touche_de_fonction_simple():
    modifiers, vk = parse_hotkey("F9")

    assert vk == VK_F1 + 8
    # MOD_NOREPEAT est toujours présent : sans lui, garder la touche
    # enfoncée enchaînerait démarrages et arrêts
    assert modifiers == MOD_NOREPEAT


def test_touche_avec_modificateurs():
    modifiers, vk = parse_hotkey("Ctrl+Shift+R")

    assert vk == ord('R')
    assert modifiers & MOD_CONTROL
    assert modifiers & MOD_SHIFT
    assert not modifiers & MOD_ALT


def test_analyse_insensible_a_la_casse():
    assert parse_hotkey("ctrl+f9") == parse_hotkey("CTRL+F9")


def test_alias_des_modificateurs():
    assert parse_hotkey("Control+A") == parse_hotkey("Ctrl+A")
    assert parse_hotkey("Windows+A") == parse_hotkey("Win+A")


def test_toutes_les_touches_de_fonction():
    for n in range(1, 25):
        _, vk = parse_hotkey(f"F{n}")
        assert vk == VK_F1 + n - 1


@pytest.mark.parametrize("libelle", [
    "", "F0", "F25", "Machin+A", "Ctrl+", "Ctrl+Machin", "+",
])
def test_libelles_invalides(libelle):
    """Un libellé incompréhensible doit donner None, jamais un raccourci
    arbitraire : l'utilisateur doit pouvoir être averti."""
    assert parse_hotkey(libelle) is None


def test_chiffre_accepte():
    _, vk = parse_hotkey("Ctrl+1")

    assert vk == ord('1')


# --- cycle de vie ---

def test_libelle_invalide_refuse_de_demarrer():
    hotkey = GlobalHotkey("Machin+Truc")

    assert hotkey.start() is False
    assert hotkey.is_active is False
    assert "incompréhensible" in hotkey.error


def test_stop_sans_start_ne_leve_pas():
    """Appelé à la fermeture de l'application, y compris si le raccourci
    n'a jamais démarré."""
    GlobalHotkey("F9").stop()


@windows_seulement
def test_enregistrement_et_liberation():
    hotkey = GlobalHotkey("F9")

    assert hotkey.start() is True
    assert hotkey.is_active is True
    hotkey.stop()
    assert hotkey.is_active is False

    # La combinaison doit être réellement libérée, sinon Lumina la
    # garderait prise jusqu'à la fin de la session Windows
    autre = GlobalHotkey("F9")
    assert autre.start() is True
    autre.stop()


@windows_seulement
def test_combinaison_deja_prise_est_signalee():
    premier = GlobalHotkey("F9")
    premier.start()
    try:
        second = GlobalHotkey("F9")

        assert second.start() is False
        assert "déjà utilisé" in second.error
        second.stop()
    finally:
        premier.stop()


@windows_seulement
def test_le_callback_est_appele_a_l_appui():
    import ctypes
    import time

    appuis = []
    hotkey = GlobalHotkey("F9", on_pressed=lambda: appuis.append(1))
    assert hotkey.start() is True

    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(0x78, 0, 0, 0)      # F9 enfoncée
        time.sleep(0.05)
        user32.keybd_event(0x78, 0, 2, 0)      # F9 relâchée

        deadline = time.time() + 2.0
        while not appuis and time.time() < deadline:
            time.sleep(0.02)

        assert appuis, "le raccourci ne s'est pas déclenché"
    finally:
        hotkey.stop()


@windows_seulement
def test_un_callback_defaillant_ne_tue_pas_le_raccourci():
    import ctypes
    import time

    appels = []

    def callback_qui_echoue():
        appels.append(1)
        raise RuntimeError("panne simulée")

    hotkey = GlobalHotkey("F9", on_pressed=callback_qui_echoue)
    assert hotkey.start() is True

    try:
        user32 = ctypes.windll.user32
        for _ in range(2):
            user32.keybd_event(0x78, 0, 0, 0)
            time.sleep(0.05)
            user32.keybd_event(0x78, 0, 2, 0)
            time.sleep(0.3)

        # Le second appui doit passer malgré l'échec du premier
        assert len(appels) >= 2
        assert hotkey.is_active
    finally:
        hotkey.stop()


def test_disponibilite_suit_la_plateforme():
    assert hotkey_is_available() == (os.name == 'nt')


def test_raccourci_par_defaut_est_analysable():
    """F9 : ni Windows ni les navigateurs ne l'utilisent, contrairement à
    F5, F11 ou F12."""
    assert parse_hotkey(DEFAULT_HOTKEY) is not None
