"""
SystemAnalyzer - Analyse des configurations système
"""

import psutil
import platform
from typing import Dict, Any, Tuple
from enum import Enum


class SystemTier(Enum):
    """Niveaux de configuration système"""
    ENTRY = "ENTRY"      # Configuration faible
    STANDARD = "STANDARD"  # Configuration moyenne
    PRO = "PRO"          # Configuration élevée


class SystemAnalyzer:
    """Classe pour analyser les performances du système"""
    
    def __init__(self):
        self.cpu_count = psutil.cpu_count(logical=True)
        self.cpu_freq = psutil.cpu_freq()
        self.ram_total = psutil.virtual_memory().total
        self.gpu_info = self._get_gpu_info()
        
    def _get_gpu_info(self) -> Dict[str, Any]:
        """Récupère les informations GPU"""
        # TODO: Implémenter avec pynvml ou pyopencl
        return {"name": "Unknown", "memory": 0}
    
    def get_system_tier(self) -> SystemTier:
        """Détermine le niveau de configuration du système"""
        ram_gb = self.ram_total / (1024 ** 3)
        
        # Critères de classification
        if ram_gb < 8 or self.cpu_count < 4:
            return SystemTier.ENTRY
        elif ram_gb < 16 or self.cpu_count < 8:
            return SystemTier.STANDARD
        else:
            return SystemTier.PRO
    
    def get_recommended_settings(self) -> Dict[str, Any]:
        """Recommande les paramètres optimaux selon la configuration"""
        tier = self.get_system_tier()
        
        if tier == SystemTier.ENTRY:
            return {
                "resolution": (1280, 720),
                "fps": 30,
                "bitrate": "2500k",
                "encoder": "software",  # x264
                "audio_gain": 0.5
            }
        elif tier == SystemTier.STANDARD:
            return {
                "resolution": (1920, 1080),
                "fps": 60,
                "bitrate": "5000k",
                "encoder": "hardware",  # NVENC/QuickSync si disponible
                "audio_gain": 0.5
            }
        else:  # PRO
            return {
                "resolution": (3840, 2160),  # 4K
                "fps": 60,
                "bitrate": "15000k",
                "encoder": "hardware",
                "audio_gain": 0.5
            }
    
    def get_current_usage(self) -> Dict[str, float]:
        """Retourne l'utilisation actuelle du système"""
        return {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "ram_percent": psutil.virtual_memory().percent,
            "ram_available_gb": psutil.virtual_memory().available / (1024 ** 3)
        }
    
    def get_system_info(self) -> Dict[str, Any]:
        """Retourne toutes les informations système"""
        return {
            "platform": platform.system(),
            "platform_release": platform.release(),
            "processor": platform.processor(),
            "cpu_count": self.cpu_count,
            "cpu_freq_mhz": self.cpu_freq.current if self.cpu_freq else 0,
            "ram_total_gb": self.ram_total / (1024 ** 3),
            "gpu": self.gpu_info,
            "tier": self.get_system_tier().value,
            "recommended": self.get_recommended_settings()
        }
