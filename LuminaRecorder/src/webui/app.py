"""
Lumina Recorder - Fenêtre de l'interface web

Ouvre la fenêtre PyWebView, y branche le pont, et gère le cycle de vie.
Toute la logique vit dans bridge.py ; ce module ne fait que l'assembler.
"""

import sys
from pathlib import Path


def assets_dir() -> Path:
    """Dossier des fichiers de l'interface.

    Empaquetée avec PyInstaller, l'application est dépliée dans un
    dossier temporaire exposé par sys._MEIPASS : le chemin du fichier
    source n'existe alors plus.
    """
    if getattr(sys, 'frozen', False):
        base = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
        return base / 'src' / 'webui' / 'assets'
    return Path(__file__).parent / 'assets'


def webview_is_available() -> tuple:
    """(disponible, raison) — pywebview et son moteur sont-ils utilisables ?

    On distingue les deux causes d'échec possibles, car elles appellent
    des réponses différentes : pywebview manquant s'installe avec pip,
    WebView2 absent demande un runtime Microsoft.
    """
    try:
        import webview  # noqa: F401
    except ImportError:
        return (False, "pywebview n'est pas installé "
                       "(pip install pywebview)")

    if sys.platform != 'win32':
        return (True, "")

    try:
        import winreg
        keys = [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
             r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
             r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
             r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        ]
        for root, path in keys:
            try:
                with winreg.OpenKey(root, path) as key:
                    version, _ = winreg.QueryValueEx(key, "pv")
                    if version:
                        return (True, "")
            except OSError:
                continue
        return (False, "Le runtime WebView2 de Microsoft est absent")
    except Exception:
        # Dans le doute on tente : un échec d'ouverture sera visible et
        # rattrapé par l'appelant
        return (True, "")


def run() -> int:
    """Lance l'interface web. Retourne un code de sortie."""
    import webview

    from webui.bridge import LuminaBridge

    bridge = LuminaBridge()
    full_w, full_h = LuminaBridge.full_size()
    index = assets_dir() / 'index.html'
    if not index.exists():
        print(f"[Lumina] Interface introuvable : {index}")
        return 1

    window = webview.create_window(
        'Lumina Recorder',
        url=str(index),
        js_api=bridge,
        width=full_w,
        height=full_h,
        # Doit rester sous la taille du widget d'enregistrement : min_size
        # est un plancher absolu que pywebview applique aussi à resize(),
        # et un plancher trop haut donnait un widget de 840×540 qui
        # masquait l'écran filmé. La taille confortable de la fenêtre est
        # garantie par `width`/`height`, pas par ce plancher.
        min_size=LuminaBridge.COMPACT_SIZE,
        background_color='#131417',
        # Bordure native conservée : elle apporte le déplacement, le
        # redimensionnement, l'ancrage Windows et l'agrandissement au
        # double-clic. Une fenêtre sans bordure n'offre rien de tout cela,
        # car « -webkit-app-region: drag » est une propriété Electron que
        # WebView2 ignore. Le widget d'enregistrement retire la bordure
        # le temps de la capture (voir LuminaBridge._set_native_frame).
        frameless=False,
        resizable=True,
        easy_drag=True,       # déplace le widget, qui lui est sans bordure
    )
    bridge._window = window

    def on_start():
        # Le raccourci est enregistré une fois la fenêtre prête : son
        # état est ensuite lu par get_initial_state
        bridge.setup_hotkey()

    def on_closing():
        # Libère le raccourci et arrête une capture en cours, sinon
        # Windows garderait la touche jusqu'à la fin de la session et le
        # thread de capture survivrait à la fenêtre
        bridge.shutdown()

    window.events.closing += on_closing

    webview.start(on_start, private_mode=False)
    return 0
