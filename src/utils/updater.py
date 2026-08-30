"""
Updater - Vérification et gestion des mises à jour automatiques
"""

import json
import urllib.request
from typing import Optional, Dict, Any
from packaging import version


class UpdateChecker:
    """Classe pour vérifier et gérer les mises à jour"""
    
    def __init__(self, current_version: str, update_url: str = ""):
        self.current_version = current_version
        self.update_url = update_url  # URL du fichier version.json
    
    def check_for_updates(self) -> Dict[str, Any]:
        """Vérifie s'il y a une mise à jour disponible"""
        try:
            # Télécharge le fichier version.json depuis le serveur
            if not self.update_url:
                return {"available": False, "reason": "Aucune URL de mise à jour configurée"}
            
            with urllib.request.urlopen(self.update_url, timeout=5) as response:
                data = json.loads(response.read().decode())
                
                latest_version = data.get("version", "0.0.0")
                
                # Compare les versions
                if version.parse(latest_version) > version.parse(self.current_version):
                    return {
                        "available": True,
                        "latest_version": latest_version,
                        "current_version": self.current_version,
                        "message": data.get("message", ""),
                        "download_url": data.get("download_url", ""),
                        "changelog": data.get("changelog", [])
                    }
                else:
                    return {"available": False, "reason": "Déjà à jour"}
                    
        except Exception as e:
            return {"available": False, "reason": f"Erreur: {str(e)}"}
    
    def download_update(self, download_url: str, save_path: str) -> bool:
        """Télécharge la mise à jour"""
        try:
            urllib.request.urlretrieve(download_url, save_path)
            return True
        except Exception:
            return False
    
    @staticmethod
    def create_version_json(version: str, message: str, download_url: str, 
                           changelog: list = None) -> Dict[str, Any]:
        """Crée un fichier version.json pour le serveur"""
        return {
            "version": version,
            "message": message,
            "download_url": download_url,
            "changelog": changelog or []
        }
