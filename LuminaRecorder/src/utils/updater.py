"""
Lumina Recorder - Update Checker
Vérifie et gère les mises à jour automatiques de l'application.
"""

import json
import urllib.request
import urllib.error
from typing import Optional, Dict
from packaging import version


class UpdateChecker:
    """
    Vérificateur de mises à jour pour Lumina.
    Compare la version locale avec celle sur le serveur.
    """
    
    # URL du fichier version.json sur votre serveur
    UPDATE_SERVER_URL = "https://votre-serveur.com/lumina/version.json"
    
    def __init__(self, current_version: str):
        self.current_version = current_version
        self.latest_version: Optional[str] = None
        self.update_info: Optional[Dict] = None
        
    def check_for_updates(self) -> bool:
        """
        Vérifie s'il y a une mise à jour disponible.
        
        Returns:
            True si une mise à jour est disponible, False sinon
        """
        try:
            # Téléchargement des informations de version
            with urllib.request.urlopen(self.UPDATE_SERVER_URL, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                
            self.latest_version = data.get('version', '0.0.0')
            self.update_info = data
            
            # Comparaison des versions
            current = version.parse(self.current_version)
            latest = version.parse(self.latest_version)
            
            return latest > current
            
        except (urllib.error.URLError, json.JSONDecodeError, Exception) as e:
            print(f"[Lumina] Impossible de vérifier les mises à jour: {e}")
            return False
            
    def get_update_details(self) -> Optional[Dict]:
        """
        Retourne les détails de la mise à jour.
        
        Returns:
            Dictionnaire avec version, notes de version, URL de téléchargement
        """
        if not self.update_info:
            return None
            
        return {
            'version': self.latest_version,
            'release_notes': self.update_info.get('release_notes', ''),
            'download_url': self.update_info.get('download_url', ''),
            'mandatory': self.update_info.get('mandatory', False),
            'release_date': self.update_info.get('release_date', '')
        }
        
    def download_installer(self, save_path: str) -> bool:
        """
        Télécharge le programme d'installation.
        
        Args:
            save_path: Chemin où sauvegarder le fichier
            
        Returns:
            True si succès, False sinon
        """
        if not self.update_info or 'download_url' not in self.update_info:
            return False
            
        try:
            download_url = self.update_info['download_url']
            
            def progress_hook(count, block_size, total_size):
                downloaded = count * block_size
                percent = min(downloaded * 100 / total_size, 100)
                print(f"\r[Lumina] Téléchargement: {percent:.1f}%", end='')
                
            urllib.request.urlretrieve(download_url, save_path)
            print("\n[Lumina] Téléchargement terminé!")
            return True
            
        except Exception as e:
            print(f"\n[Lumina] Erreur de téléchargement: {e}")
            return False


# Exemple de structure du fichier version.json à héberger sur votre serveur:
"""
{
    "version": "1.1.0",
    "release_notes": "Nouveautés:\n- Smart Focus activé\n- Correction de bugs\n- Amélioration des performances",
    "download_url": "https://votre-serveur.com/lumina/Lumina_Setup_1.1.0.exe",
    "mandatory": false,
    "release_date": "2025-01-15"
}
"""


if __name__ == "__main__":
    # Test rapide
    checker = UpdateChecker(current_version="1.0.0")
    
    print("Vérification des mises à jour...")
    if checker.check_for_updates():
        details = checker.get_update_details()
        print(f"\n✓ Nouvelle version disponible: {details['version']}")
        print(f"Notes: {details['release_notes']}")
    else:
        print("✓ Vous utilisez la dernière version.")
