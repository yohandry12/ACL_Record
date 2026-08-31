"""
Lumina Recorder - Main Entry Point
Point d'entrée principal de l'application.
"""

import io
import sys
from pathlib import Path


def _make_output_safe():
    """Empêche un print d'accents de tuer l'application.

    La console Windows utilise cp1252, qui ne connaît ni « ╔ » ni « ✨ ».
    Un print de ces caractères lève UnicodeEncodeError, et comme les
    messages du projet sont en français (« Enregistrement arrêté »,
    « Smart Focus : suivi de … »), n'importe lequel peut faire tomber
    l'application entière — c'est ce qui empêchait l'exécutable
    d'afficher sa fenêtre.

    Empaquetée avec --windowed, l'application n'a même pas de console :
    stdout vaut None et tout print lève AttributeError. On fournit alors
    un puits neutre.
    """
    for name in ('stdout', 'stderr'):
        stream = getattr(sys, name, None)
        if stream is None:
            # --windowed : aucune console rattachée
            setattr(sys, name, io.StringIO())
            continue
        try:
            # errors='replace' : un caractère non représentable devient
            # « ? » au lieu de lever
            stream.reconfigure(errors='replace')
        except Exception:
            pass


_make_output_safe()

# Ajout du dossier src au path pour les imports.
# Empaquetée avec PyInstaller, l'application est dépliée dans un dossier
# temporaire exposé par sys._MEIPASS : le chemin du fichier source
# n'existe alors plus.
if getattr(sys, 'frozen', False):
    src_path = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent)) / 'src'
else:
    src_path = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_path))

from core.window_detect import enable_dpi_awareness

# Doit précéder la création de la fenêtre Tk : Windows refuse tout
# changement d'échelle une fois la première fenêtre créée. Sans cela, sur
# un écran mis à l'échelle (150 %...), les coordonnées de fenêtre et les
# pixels capturés ne sont pas dans le même repère et le Smart Focus filme
# à côté.
enable_dpi_awareness()

def run_classic():
    """Interface tkinter historique."""
    from ui.main_window import MainWindow
    MainWindow().run()


def main():
    """Fonction principale de lancement"""
    from version import __version__
    print("╔════════════════════════════════════╗")
    print(f"║     ✨ LUMINA RECORDER v{__version__:<10s} ║")
    print("║  Capturez votre monde en clarté    ║")
    print("╚════════════════════════════════════╝")
    print()

    try:
        # --diag-ai : imprime la disponibilité des briques IA puis sort.
        # C'est le seul moyen honnête de vérifier qu'un exe empaqueté
        # embarque réellement Whisper et l'OCR : les imports gardés
        # rendent l'application muette sur ce qui manque.
        if '--diag-ai' in sys.argv:
            import json
            from postprocess.subtitles_processor import whisper_is_available
            from services.ocr_service import ocr_is_available
            print(json.dumps({
                'whisper': whisper_is_available(),
                'ocr': ocr_is_available(),
            }))
            return 0

        # --classic force l'ancienne interface. Elle est conservée le
        # temps que la nouvelle soit éprouvée à l'usage : un défaut
        # bloquant ne doit laisser personne sans application utilisable.
        if '--classic' in sys.argv:
            run_classic()
            return 0

        from webui.app import run, webview_is_available
        available, reason = webview_is_available()
        if not available:
            # Repli plutôt que plantage : mieux vaut l'ancienne interface
            # qu'aucune interface, et l'utilisateur doit savoir pourquoi
            print(f"[Lumina] Interface web indisponible : {reason}")
            print("[Lumina] Bascule sur l'interface classique.")
            run_classic()
            return 0

        return run()


    except KeyboardInterrupt:
        print("\n[Lumina] Application fermée par l'utilisateur.")
    except Exception as e:
        print(f"\n[Lumina] Erreur critique: {e}")
        import traceback
        traceback.print_exc()
        # Empaquetée avec --windowed, il n'y a aucune console pour lire
        # ce message : sans boîte de dialogue, l'application semblerait
        # simplement ne pas se lancer.
        if getattr(sys, 'frozen', False):
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    None, f"{e}\n\n{traceback.format_exc()}",
                    "Lumina Recorder - Erreur au démarrage", 0x10)
            except Exception:
                pass
        return 1
        
    return 0


if __name__ == "__main__":
    sys.exit(main())
