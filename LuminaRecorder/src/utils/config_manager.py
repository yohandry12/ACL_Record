"""
Lumina Recorder - Configuration Manager
Gère la lecture et l'écriture des paramètres utilisateur.
"""

import configparser
import os
from pathlib import Path
from typing import Any, Optional


class ConfigManager:
    """
    Gestionnaire de configuration pour Lumina.
    Sauvegarde les préférences dans un fichier INI.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            # Chemin par défaut dans AppData (Windows) ou ~/.config (Linux/Mac)
            if os.name == 'nt':  # Windows
                base_dir = Path(os.environ.get('APPDATA', '')) / 'LuminaRecorder'
            else:
                base_dir = Path.home() / '.config' / 'lumina_recorder'
                
            base_dir.mkdir(parents=True, exist_ok=True)
            self.config_path = base_dir / 'lumina_config.ini'
        else:
            self.config_path = Path(config_path)
            
        self.config = configparser.ConfigParser()
        self._load_or_create_config()
        
    def _load_or_create_config(self):
        """Charge la configuration existante ou crée une nouvelle"""
        if self.config_path.exists():
            self.config.read(self.config_path, encoding='utf-8')
        else:
            # Charger la configuration par défaut depuis le projet
            default_config_path = Path(__file__).parent.parent.parent / 'config' / 'default_config.ini'
            if default_config_path.exists():
                self.config.read(default_config_path, encoding='utf-8')
            self.save()
            
    def get(self, section: str, key: str, fallback: Any = None) -> Any:
        """Récupère une valeur de configuration"""
        try:
            return self.config.get(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback
            
    def get_int(self, section: str, key: str, fallback: int = 0) -> int:
        """Récupère une valeur entière"""
        try:
            return self.config.getint(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback
            
    def get_float(self, section: str, key: str, fallback: float = 0.0) -> float:
        """Récupère une valeur flottante"""
        try:
            return self.config.getfloat(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback
            
    def get_bool(self, section: str, key: str, fallback: bool = False) -> bool:
        """Récupère une valeur booléenne"""
        try:
            return self.config.getboolean(section, key)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback
            
    def set(self, section: str, key: str, value: Any):
        """Définit une valeur de configuration"""
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, key, str(value))
        self.save()
        
    def save(self):
        """Sauvegarde la configuration sur disque"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self.config.write(f)
            
    def reset_to_defaults(self):
        """Réinitialise la configuration aux valeurs par défaut"""
        default_config_path = Path(__file__).parent.parent.parent / 'config' / 'default_config.ini'
        if default_config_path.exists():
            self.config.read(default_config_path, encoding='utf-8')
            self.save()
            
    def get_all_settings(self) -> dict:
        """Retourne tous les paramètres sous forme de dictionnaire"""
        settings = {}
        for section in self.config.sections():
            settings[section] = dict(self.config.items(section))
        return settings


if __name__ == "__main__":
    # Test rapide
    cfg = ConfigManager()
    print("Configuration chargée depuis:", cfg.config_path)
    print("Nom de l'app:", cfg.get('general', 'app_name'))
    print("Version:", cfg.get('general', 'version'))
    print("Tous les paramètres:", cfg.get_all_settings())
