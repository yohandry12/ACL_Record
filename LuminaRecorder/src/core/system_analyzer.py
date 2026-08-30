"""
Lumina Recorder - System Analyzer Module
Analyse les configurations matérielles pour adapter les paramètres d'enregistrement.
"""

import psutil
import platform
import subprocess
import re
from typing import Dict, Tuple, Optional
from enum import Enum


class SystemProfile(Enum):
    """Profils système détectés"""
    ENTRY = "ENTRY"      # Configuration faible
    STANDARD = "STANDARD"  # Configuration moyenne
    PRO = "PRO"          # Configuration élevée


class SystemAnalyzer:
    """
    Analyseur de système intelligent pour Lumina.
    Détecte CPU, RAM, GPU et recommande les meilleurs paramètres.
    """
    
    def __init__(self):
        self.cpu_count = psutil.cpu_count(logical=True)
        self.cpu_freq = psutil.cpu_freq()
        self.ram_total = psutil.virtual_memory().total / (1024 ** 3)  # En Go
        self.platform_system = platform.system()
        self.profile = self.detect_profile()
        
    def get_cpu_info(self) -> Dict:
        """Récupère les informations CPU"""
        return {
            'cores': self.cpu_count,
            'frequency': f"{self.cpu_freq.current:.2f} MHz" if self.cpu_freq else 'N/A',
            'usage': psutil.cpu_percent(interval=1)
        }
    
    def get_ram_info(self) -> Dict:
        """Récupère les informations RAM"""
        ram = psutil.virtual_memory()
        return {
            'total_gb': round(self.ram_total, 2),
            'available_gb': round(ram.available / (1024 ** 3), 2),
            'usage_percent': ram.percent
        }
    
    def get_gpu_info(self) -> Dict:
        """Tente de récupérer les informations GPU"""
        gpu_info = {'detected': False, 'name': 'Unknown', 'vram': 'N/A'}
        
        try:
            # Windows: PowerShell pour WMI
            if self.platform_system == "Windows":
                cmd = 'powershell "Get-WmiObject Win32_VideoController | Select-Object Name, AdapterRAM"'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    output = result.stdout
                    lines = [l.strip() for l in output.split('\n') if l.strip()]
                    if len(lines) >= 2:
                        # Parsing basique
                        name_line = lines[1]
                        gpu_info['detected'] = True
                        gpu_info['name'] = name_line.split(':')[1].strip() if ':' in name_line else 'Unknown'
                        
            # Linux: lspci
            elif self.platform_system == "Linux":
                cmd = "lspci | grep -i vga"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout:
                    gpu_info['detected'] = True
                    gpu_info['name'] = result.stdout.strip().split(':')[-1].strip()
                    
            # macOS: system_profiler
            elif self.platform_system == "Darwin":
                cmd = "system_profiler SPDisplaysDataType | grep 'Chipset Model'"
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout:
                    gpu_info['detected'] = True
                    gpu_info['name'] = result.stdout.strip().split(':')[-1].strip()
                    
        except Exception as e:
            print(f"[Lumina] Impossible de détecter le GPU: {e}")
            
        return gpu_info
    
    def detect_profile(self) -> SystemProfile:
        """
        Détermine le profil système basé sur le matériel.
        
        Critères:
        - ENTRY: < 4 cœurs OU < 8Go RAM
        - STANDARD: 4-8 cœurs ET 8-16Go RAM
        - PRO: > 8 cœurs ET > 16Go RAM
        """
        cpu_score = self.cpu_count
        ram_score = self.ram_total
        
        if cpu_score >= 8 and ram_score >= 16:
            return SystemProfile.PRO
        elif cpu_score >= 4 and ram_score >= 8:
            return SystemProfile.STANDARD
        else:
            return SystemProfile.ENTRY
    
    def get_recommended_settings(self) -> Dict:
        """
        Retourne les paramètres recommandés selon le profil.
        """
        settings = {
            'profile': self.profile.value,
            'resolution': '1920x1080',
            'fps': 30,
            'bitrate': '5000k',
            'encoder': 'software',  # software ou hardware
            'audio_channels': 2
        }
        
        if self.profile == SystemProfile.ENTRY:
            settings.update({
                'resolution': '1280x720',
                'fps': 30,
                'bitrate': '2500k',
                'encoder': 'software',
                'note': 'Mode optimisé pour performances'
            })
        elif self.profile == SystemProfile.STANDARD:
            settings.update({
                'resolution': '1920x1080',
                'fps': 60,
                'bitrate': '6000k',
                'encoder': 'hardware' if self._has_hardware_encoder() else 'software',
                'note': 'Mode équilibré'
            })
        elif self.profile == SystemProfile.PRO:
            settings.update({
                'resolution': '3840x2160',  # 4K
                'fps': 60,
                'bitrate': '15000k',
                'encoder': 'hardware' if self._has_hardware_encoder() else 'software',
                'note': 'Mode haute qualité activé'
            })
            
        return settings
    
    def _has_hardware_encoder(self) -> bool:
        """Vérifie si un encodeur matériel (NVENC, QSV, VCE) est disponible"""
        gpu_info = self.get_gpu_info()
        name = gpu_info.get('name', '').lower()
        
        # NVIDIA NVENC
        if 'nvidia' in name or 'geforce' in name or 'quadro' in name:
            return True
        # Intel QuickSync
        if 'intel' in name and ('uhd' in name or 'iris' in name or 'hd graphics' in name):
            return True
        # AMD VCE/VCN
        if 'amd' in name or 'radeon' in name:
            return True
            
        return False
    
    def get_system_summary(self) -> str:
        """Retourne un résumé lisible du système"""
        cpu = self.get_cpu_info()
        ram = self.get_ram_info()
        gpu = self.get_gpu_info()
        
        summary = f"""
=== RAPPORT SYSTÈME LUMINA ===
Profil détecté : {self.profile.value}
-----------------------------
CPU : {cpu['cores']} cœurs | {cpu['frequency']}
RAM : {ram['total_gb']} Go ({ram['usage_percent']}% utilisé)
GPU : {gpu['name'] if gpu['detected'] else 'Non détecté'}
-----------------------------
Recommandation : {self.get_recommended_settings()['note']}
================================
"""
        return summary


if __name__ == "__main__":
    # Test rapide du module
    analyzer = SystemAnalyzer()
    print(analyzer.get_system_summary())
    print("\nParamètres recommandés :", analyzer.get_recommended_settings())
