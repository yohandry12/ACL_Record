"""
Lumina Recorder - Raccourci clavier global (Windows)

Permet de démarrer et d'arrêter l'enregistrement sans revenir sur la
fenêtre de Lumina. Indispensable dès qu'on enregistre en plein écran ou
avec le Smart Focus : cliquer sur le bouton ARRÊTER obligerait sinon à
faire passer Lumina au premier plan, ce qui apparaît dans la vidéo.

Pourquoi RegisterHotKey et pas un hook clavier
-----------------------------------------------
La bibliothèque `keyboard` (et tout hook WH_KEYBOARD_LL) intercepte
TOUTES les frappes du système et réclame les droits administrateur sous
Windows. Pour une application distribuée, c'est à la fois excessif en
privilèges et suspect pour un antivirus. RegisterHotKey est l'API prévue
pour cet usage : le système ne nous réveille que pour la combinaison
demandée, sans privilège particulier et sans voir les autres touches.

Pourquoi un thread dédié
------------------------
RegisterHotKey livre WM_HOTKEY dans la file de messages du thread qui a
enregistré le raccourci, et ce thread doit tourner une boucle de messages
Windows. tkinter a déjà la sienne, incompatible. On isole donc la boucle
Windows dans son propre thread, qui ne fait que recevoir la touche et
appeler un callback ; c'est à l'appelant de repasser dans le thread
tkinter (root.after) avant de toucher à l'interface.
"""

import ctypes
import os
import threading
from ctypes import wintypes
from typing import Callable, Optional

# Modificateurs de RegisterHotKey (winuser.h)
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
# Empêche la répétition automatique quand la touche reste enfoncée :
# sans lui, garder F9 appuyé enchaînerait démarrages et arrêts
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# Codes des touches de fonction (Virtual-Key Codes)
VK_F1 = 0x70

# Raccourci par défaut : F9, seul, sans modificateur. Choisi parce qu'il
# n'est utilisé ni par Windows ni par les navigateurs, contrairement à
# F5 (rafraîchir), F11 (plein écran) ou F12 (outils de développement).
DEFAULT_HOTKEY = "F9"


def hotkey_is_available() -> bool:
    """True si les raccourcis globaux sont utilisables (Windows)."""
    return os.name == 'nt'


def parse_hotkey(label: str) -> Optional[tuple]:
    """Traduit un libellé lisible en (modificateurs, code de touche).

    Accepte "F9", "Ctrl+F9", "Ctrl+Shift+R"... Retourne None si le
    libellé est incompréhensible, pour que l'appelant puisse le signaler
    au lieu d'enregistrer un raccourci arbitraire.

    >>> parse_hotkey("Ctrl+F9") == (MOD_CONTROL | MOD_NOREPEAT, VK_F1 + 8)
    True
    """
    if not label:
        return None

    modifiers = MOD_NOREPEAT
    parts = [p.strip() for p in label.split('+') if p.strip()]
    if not parts:
        return None

    known_modifiers = {
        'ctrl': MOD_CONTROL, 'control': MOD_CONTROL,
        'alt': MOD_ALT,
        'shift': MOD_SHIFT,
        'win': MOD_WIN, 'windows': MOD_WIN,
    }

    key_part = parts[-1].lower()
    for part in parts[:-1]:
        mod = known_modifiers.get(part.lower())
        if mod is None:
            return None
        modifiers |= mod

    # Touche de fonction : F1 à F24
    if key_part.startswith('f') and key_part[1:].isdigit():
        number = int(key_part[1:])
        if 1 <= number <= 24:
            return (modifiers, VK_F1 + number - 1)
        return None

    # Lettre ou chiffre : le code virtuel correspond au caractère majuscule
    if len(key_part) == 1 and key_part.isalnum():
        return (modifiers, ord(key_part.upper()))

    return None


class GlobalHotkey:
    """Raccourci clavier global, actif tant que l'application tourne.

    Utilisation :
        hotkey = GlobalHotkey("F9", on_pressed=basculer)
        hotkey.start()
        ...
        hotkey.stop()

    Le callback est appelé depuis le thread du raccourci, JAMAIS depuis
    le thread tkinter : l'appelant doit repasser par root.after avant de
    toucher à l'interface.
    """

    def __init__(self, label: str = DEFAULT_HOTKEY,
                 on_pressed: Optional[Callable[[], None]] = None):
        self.label = label
        self.on_pressed = on_pressed
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._running = False
        # Signale que l'enregistrement auprès de Windows a abouti ou
        # échoué : start() attend ce résultat pour pouvoir le retourner
        self._registered = threading.Event()
        self._registration_ok = False
        self.error: str = ""

    @property
    def is_active(self) -> bool:
        """True si le raccourci est effectivement enregistré."""
        return self._running and self._registration_ok

    def start(self) -> bool:
        """Enregistre le raccourci auprès de Windows.

        Returns:
            True si le raccourci est actif. False si la plateforme ne le
            permet pas, si le libellé est invalide, ou si la combinaison
            est déjà prise par une autre application — dans ce dernier
            cas `error` explique lequel.
        """
        if self._running:
            return self.is_active

        if not hotkey_is_available():
            self.error = "Les raccourcis globaux ne sont gérés que sous Windows"
            return False

        if parse_hotkey(self.label) is None:
            self.error = f"Raccourci « {self.label} » incompréhensible"
            return False

        self._running = True
        self._registered.clear()
        self._thread = threading.Thread(target=self._message_loop,
                                        name="LuminaHotkey", daemon=True)
        self._thread.start()

        # L'enregistrement est presque instantané ; le délai n'est là que
        # pour ne jamais bloquer le démarrage de l'application
        self._registered.wait(timeout=2.0)
        if not self._registration_ok:
            self._running = False
        return self._registration_ok

    def stop(self):
        """Libère le raccourci et arrête le thread."""
        if not self._running:
            return

        self._running = False
        # Réveille la boucle de messages, qui est bloquée dans GetMessage
        if self._thread_id is not None:
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass

        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = None
        self._registration_ok = False

    def _message_loop(self):
        """Boucle de messages Windows du thread dédié.

        Le raccourci DOIT être enregistré et libéré depuis ce même thread :
        Windows attache le raccourci au thread appelant.
        """
        # use_last_error : sans lui, GetLastError() renvoie une valeur
        # écrasée par les appels ctypes internes et le diagnostic
        # « raccourci déjà pris » serait faux
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        hotkey_id = 1
        parsed = parse_hotkey(self.label)

        try:
            self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            modifiers, vk = parsed

            if not user32.RegisterHotKey(None, hotkey_id, modifiers, vk):
                # Erreur 1409 = ERROR_HOTKEY_ALREADY_REGISTERED : une
                # autre application a déjà pris cette combinaison
                code = ctypes.get_last_error()  # via use_last_error
                if code == 1409:
                    self.error = (f"Le raccourci {self.label} est déjà "
                                  f"utilisé par une autre application")
                else:
                    self.error = (f"Impossible d'enregistrer {self.label} "
                                  f"(erreur Windows {code})")
                return

            self._registration_ok = True
        except Exception as e:
            self.error = f"Raccourci indisponible ({e})"
            return
        finally:
            # Toujours signalé : sans cela, start() attendrait son délai
            # complet à chaque échec
            self._registered.set()

        try:
            msg = wintypes.MSG()
            while self._running:
                # GetMessage bloque jusqu'à l'arrivée d'un message : ce
                # thread ne consomme aucun CPU en attente
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result in (0, -1):   # WM_QUIT ou erreur
                    break
                if msg.message == WM_HOTKEY and self.on_pressed:
                    try:
                        self.on_pressed()
                    except Exception as e:
                        # Un callback défaillant ne doit pas tuer le
                        # raccourci pour le reste de la session
                        print(f"[Lumina] Erreur dans le raccourci : {e}")
        finally:
            try:
                user32.UnregisterHotKey(None, hotkey_id)
            except Exception:
                pass
