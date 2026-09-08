"""
Lumina Recorder - Fenêtre de l'interface web

Ouvre la fenêtre PyWebView, y branche le pont, et gère le cycle de vie.
Toute la logique vit dans bridge.py ; ce module ne fait que l'assembler.
"""

import os
import shutil
import sys
from pathlib import Path


def webview_storage_path() -> Path:
    """Dossier du profil WebView2, fixe et propre à l'utilisateur.

    Un profil fixe évite le dossier temporaire du mode privé, que
    pywebview tente de supprimer à la fermeture alors que Crashpad
    (le collecteur de plantages de WebView2) tient encore
    « EBWebView\\CrashpadMetrics-active.pma » ouvert : d'où le
    « [pywebview] Failed to delete user data folder: [WinError 5] » à
    chaque sortie.
    """
    base = os.environ.get('LOCALAPPDATA')
    racine = Path(base) if base else Path.home() / 'AppData' / 'Local'
    return racine / 'LuminaRecorder' / 'webview'


def purger_profil_webview_si_nouvelle_version(storage_path, version) -> bool:
    """Vide le profil WebView2 si la version de Lumina a changé.

    Remplace le profil jetable : un profil persistant a servi une page
    périmée après une mise à jour (WebView2 gardait l'index.html en
    cache et l'utilisateur voyait l'ancienne interface). On purge donc
    au changement de version uniquement, et **avant** la création de la
    fenêtre : à cet instant aucun fichier n'est encore verrouillé.

    Toute erreur est tolérée et journalisée : un profil qu'on n'a pas pu
    purger n'est pas une raison d'empêcher l'application de démarrer.

    Returns:
        True si le profil a effectivement été purgé.
    """
    dossier = Path(storage_path)
    marqueur = dossier / 'version.txt'

    try:
        dossier.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[Lumina] Profil WebView2 inaccessible ({e})")
        return False

    try:
        connue = marqueur.read_text(encoding='utf-8').strip()
    except Exception:
        # Fichier absent, illisible ou verrouillé : on considère le
        # profil comme périmé, c'est le choix sûr
        connue = None

    if connue == str(version):
        return False

    purge = False
    for entree in _contenu(dossier):
        if entree.name == marqueur.name:
            continue
        try:
            if entree.is_dir():
                shutil.rmtree(entree, ignore_errors=True)
            else:
                entree.unlink()
            purge = True
        except Exception as e:
            print(f"[Lumina] Profil WebView2 : « {entree.name} » "
                  f"non supprimé ({e})")

    try:
        marqueur.write_text(str(version), encoding='utf-8')
    except Exception as e:
        print(f"[Lumina] Profil WebView2 : version non écrite ({e})")

    if purge:
        print(f"[Lumina] Profil WebView2 purgé "
              f"(version {connue!r} → {version})")
    return purge


def _contenu(dossier: Path) -> list:
    """Entrées du dossier, liste vide si illisible (jamais d'exception)."""
    try:
        return list(dossier.iterdir())
    except Exception:
        return []


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

    from version import __version__
    from webui.bridge import LuminaBridge

    # Profil fixe, purgé au changement de version : voir
    # purger_profil_webview_si_nouvelle_version. La purge a lieu ICI,
    # avant create_window : passé ce point WebView2 tient ses fichiers.
    storage_path = webview_storage_path()
    purger_profil_webview_si_nouvelle_version(storage_path, __version__)

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

    # Profil fixe plutôt que jetable : en mode privé, pywebview
    # crée un profil temporaire qu'il supprime à la sortie, alors que
    # Crashpad tient encore CrashpadMetrics-active.pma — d'où le
    # « Failed to delete user data folder: [WinError 5] » à chaque
    # fermeture. La page périmée après mise à jour, motif initial du
    # profil jetable, est traitée par la purge au changement de version
    # faite plus haut.
    webview.start(on_start, private_mode=False,
                  storage_path=str(storage_path))
    return 0
