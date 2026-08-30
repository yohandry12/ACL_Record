"""
ConfigManager - Gestion de la configuration et des paramètres utilisateur
"""

import json
import os
from typing import Dict, Any, Optional
from pathlib import Path


class ConfigManager:
    """Classe pour gérer la configuration de l'application"""
    
    DEFAULT_CONFIG = {
        "resolution": "1920x1080 (Full HD)",
        "fps": 30,
        "bitrate": "5000k",
        "audio_gain": 0.5,
        "output_folder": str(Path.home() / "Videos"),
        "theme": "dark",
        "auto_analyze": True,
        "check_updates": True
    }
    
    def __init__(self, config_file: str = "config.json"):
        self.config_file = config_file
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """Charge la configuration depuis le fichier"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    saved_config = json.load(f)
                    # Fusionne avec la config par défaut
                    return {**self.DEFAULT_CONFIG, **saved_config}
            except (json.JSONDecodeError, IOError):
                pass
        
        return self.DEFAULT_CONFIG.copy()
    
    def save_config(self) -> bool:
        """Sauvegarde la configuration dans le fichier"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except IOError:
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """Récupère une valeur de configuration"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        """Définit une valeur de configuration"""
        self.config[key] = value
    
    def reset_to_defaults(self) -> None:
        """Réinitialise la configuration aux valeurs par défaut"""
        self.config = self.DEFAULT_CONFIG.copy()
    
    def get_all(self) -> Dict[str, Any]:
        """Retourne toute la configuration"""
        return self.config.copy()
