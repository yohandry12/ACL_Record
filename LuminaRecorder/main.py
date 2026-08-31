"""
Lumina Recorder - Main Entry Point
Point d'entrée principal de l'application.
"""

import sys
from pathlib import Path

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

from ui.main_window import MainWindow


def main():
    """Fonction principale de lancement"""
    print("╔════════════════════════════════════╗")
    print("║     ✨ LUMINA RECORDER v1.0.0      ║")
    print("║  Capturez votre monde en clarté    ║")
    print("╚════════════════════════════════════╝")
    print()
    
    try:
        # Lancement de l'interface graphique
        app = MainWindow()
        app.run()
        
    except KeyboardInterrupt:
        print("\n[Lumina] Application fermée par l'utilisateur.")
    except Exception as e:
        print(f"\n[Lumina] Erreur critique: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    return 0


if __name__ == "__main__":
    sys.exit(main())
