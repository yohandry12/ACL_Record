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
    index = assets_dir() / 'index.html'
    if not index.exists():
        print(f"[Lumina] Interface introuvable : {index}")
        return 1

    window = webview.create_window(
        'Lumina Recorder',
        url=str(index),
        js_api=bridge,
        width=LuminaBridge.CAPSULE_SIZE[0],
        height=LuminaBridge.CAPSULE_SIZE[1],
        # Plancher = le widget : pywebview l'applique aussi à resize()
        min_size=LuminaBridge.COMPACT_SIZE,
        background_color='#0D0E11',
        # La capsule est la fenêtre : pas de cadre Windows. Le
        # déplacement passe par les zones portant la classe
        # pywebview-drag-region (voir index.html) — pas par easy_drag,
        # qui saisirait aussi les boutons et les curseurs. Vérifié sur
        # cette machine : « -webkit-app-region » est une propriété
        # Electron que WebView2 ignore, la classe pywebview fonctionne.
        frameless=True,
        easy_drag=False,
        resizable=False,
    )
    bridge._window = window

    def on_start():
        # La taille de création est fausse sur une fenêtre sans cadre :
        # corrigée ici, avec les coins arrondis
        bridge.preparer_fenetre()
        # Le raccourci est enregistré une fois la fenêtre prête : son
        # état est ensuite lu par get_initial_state
        bridge.setup_hotkey()
        # Vérification des mises à jour : en arrière-plan, silencieuse
        bridge.start_update_watch()

    def on_closing():
        # Libère le raccourci et arrête une capture en cours, sinon
        # Windows garderait la touche jusqu'à la fin de la session et le
        # thread de capture survivrait à la fenêtre
        bridge.shutdown()

    window.events.closing += on_closing

    webview.start(on_start, private_mode=False)
    return 0
