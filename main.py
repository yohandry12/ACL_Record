"""
main.py - Point d'entrée principal de l'application ScreenRecorder Pro
"""

import tkinter as tk
from src.ui.main_window import MainWindow
from src.core.system_analyzer import SystemAnalyzer
from src.utils.config import ConfigManager
from src.utils.updater import UpdateChecker
from src import __version__


def main():
    """Fonction principale de lancement de l'application"""
    
    # Initialiser la fenêtre principale
    root = tk.Tk()
    
    # Charger la configuration
    config = ConfigManager()
    
    # Appliquer le thème sauvegardé
    theme_name = config.get("theme", "dark")
    
    # Vérifier les mises à jour (optionnel)
    if config.get("check_updates", True):
        updater = UpdateChecker(__version__)
        # TODO: Configurer l'URL de mise à jour
        # update_result = updater.check_for_updates()
    
    # Analyser le système au démarrage
    analyzer = SystemAnalyzer()
    system_info = analyzer.get_system_info()
    print(f"📊 Système détecté: {system_info['tier']}")
    print(f"💾 RAM: {system_info['ram_total_gb']:.1f} GB")
    print(f"🖥️ CPU: {system_info['cpu_count']} cœurs")
    
    # Paramètres recommandés
    recommended = system_info['recommended']
    print(f"⚙️ Paramètres recommandés:")
    print(f"   Résolution: {recommended['resolution'][0]}x{recommended['resolution'][1]}")
    print(f"   FPS: {recommended['fps']}")
    print(f"   Bitrate: {recommended['bitrate']}")
    
    # Créer et afficher l'interface
    app = MainWindow(root)
    
    # Lancer la boucle principale
    root.mainloop()


if __name__ == "__main__":
    main()
