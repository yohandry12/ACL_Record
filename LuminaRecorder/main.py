"""
Lumina Recorder - Main Entry Point
Point d'entrée principal de l'application.
"""

import sys
from pathlib import Path

# Ajout du dossier src au path pour les imports
src_path = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_path))

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
