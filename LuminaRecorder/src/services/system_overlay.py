"""
System Overlay Service - Affichage des Métriques Système

Affiche en temps réel pendant l'enregistrement :
- Utilisation CPU (%)
- Mémoire RAM utilisée/disponible
- Température CPU/GPU (si disponible)
- FPS d'enregistrement
- Débit vidéo (bitrate)
- Espace disque restant

Personnalisable :
- Position (coins, bords)
- Style (texte, graphiques, jauges)
- Fréquence de mise à jour
- Couleurs et polices
"""

import cv2
import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
import time
import psutil


@dataclass
class OverlayConfig:
    """Configuration de l'overlay"""
    position: str = 'top_right'  # top_left, top_right, bottom_left, bottom_right
    show_cpu: bool = True
    show_ram: bool = True
    show_fps: bool = True
    show_disk: bool = True
    show_temperature: bool = False
    font_scale: float = 0.6
    font_thickness: int = 2
    text_color: Tuple[int, int, int] = (255, 255, 255)  # Blanc BGR
    bg_color: Tuple[int, int, int] = (0, 0, 0)  # Noir
    bg_alpha: float = 0.7  # Transparence du fond
    update_interval: float = 1.0  # secondes


class SystemOverlayService:
    """
    Service d'affichage des métriques système en overlay
    
    Utilise psutil pour les métriques système
    """
    
    def __init__(self, config: Optional[OverlayConfig] = None):
        self.config = config or OverlayConfig()
        self.enabled = True
        
        # Métriques en cache
        self.metrics: Dict[str, any] = {}
        self.last_update = 0
        self.fps_history: list = []
        
        # Initialisation des compteurs
        self.frame_count = 0
        self.fps_start_time = time.time()
        self.current_fps = 0
    
    def get_cpu_usage(self) -> float:
        """Retourne l'utilisation CPU en %"""
        return psutil.cpu_percent(interval=0.1)
    
    def get_ram_usage(self) -> Dict[str, any]:
        """Retourne les statistiques RAM"""
        ram = psutil.virtual_memory()
        return {
            'percent': ram.percent,
            'used_gb': ram.used / (1024 ** 3),
            'available_gb': ram.available / (1024 ** 3),
            'total_gb': ram.total / (1024 ** 3)
        }
    
    def get_disk_usage(self, path: str = '/') -> Dict[str, any]:
        """Retourne l'utilisation du disque"""
        try:
            disk = psutil.disk_usage(path)
            return {
                'percent': disk.percent,
                'free_gb': disk.free / (1024 ** 3),
                'total_gb': disk.total / (1024 ** 3)
            }
        except Exception:
            return {'percent': 0, 'free_gb': 0, 'total_gb': 0}
    
    def get_temperature(self) -> Dict[str, float]:
        """
        Tente de récupérer les températures
        (fonctionne sur certains systèmes Linux avec lm-sensors)
        """
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                # Prendre la première température disponible
                for name, entries in temps.items():
                    if entries:
                        return {
                            'cpu': entries[0].current,
                            'high': entries[0].high,
                            'critical': entries[0].critical
                        }
        except Exception:
            pass
        return {'cpu': None, 'high': None, 'critical': None}
    
    def update_fps(self):
        """Met à jour le calcul des FPS"""
        current_time = time.time()
        self.frame_count += 1
        
        # Recalculer chaque seconde
        if current_time - self.fps_start_time >= 1.0:
            self.current_fps = self.frame_count / (current_time - self.fps_start_time)
            self.frame_count = 0
            self.fps_start_time = current_time
    
    def update_metrics(self):
        """Met à jour toutes les métriques"""
        current_time = time.time()
        
        if current_time - self.last_update < self.config.update_interval:
            return
        
        self.last_update = current_time
        
        # CPU
        if self.config.show_cpu:
            self.metrics['cpu'] = self.get_cpu_usage()
        
        # RAM
        if self.config.show_ram:
            self.metrics['ram'] = self.get_ram_usage()
        
        # Disque
        if self.config.show_disk:
            self.metrics['disk'] = self.get_disk_usage()
        
        # Température
        if self.config.show_temperature:
            self.metrics['temp'] = self.get_temperature()
        
        # FPS
        if self.config.show_fps:
            self.update_fps()
            self.metrics['fps'] = self.current_fps
    
    def draw_overlay(self, frame: np.ndarray) -> np.ndarray:
        """
        Dessine l'overlay sur la frame
        
        Args:
            frame: Image sur laquelle dessiner
            
        Returns:
            Image avec l'overlay
        """
        if not self.enabled:
            return frame
        
        self.update_metrics()
        
        result = frame.copy()
        
        # Construire les lignes de texte
        lines = []
        
        if self.config.show_cpu and 'cpu' in self.metrics:
            cpu_val = self.metrics['cpu']
            color = (0, 255, 0) if cpu_val < 70 else (0, 165, 255) if cpu_val < 90 else (0, 0, 255)
            lines.append(('CPU', f'{cpu_val:.1f}%', color))
        
        if self.config.show_ram and 'ram' in self.metrics:
            ram = self.metrics['ram']
            lines.append(('RAM', f'{ram["used_gb"]:.1f}/{ram["total_gb"]:.1f} GB ({ram["percent"]:.0f}%)', 
                         self.config.text_color))
        
        if self.config.show_fps and 'fps' in self.metrics:
            fps_val = self.metrics['fps']
            color = (0, 255, 0) if fps_val >= 24 else (0, 165, 255) if fps_val >= 15 else (0, 0, 255)
            lines.append(('FPS', f'{fps_val:.1f}', color))
        
        if self.config.show_disk and 'disk' in self.metrics:
            disk = self.metrics['disk']
            color = (0, 255, 0) if disk['percent'] < 70 else (0, 0, 255)
            lines.append(('DISK', f'{disk["free_gb"]:.0f} GB libre ({100-disk["percent"]:.0f}%)', color))
        
        if self.config.show_temperature and 'temp' in self.metrics and self.metrics['temp'].get('cpu'):
            temp = self.metrics['temp']['cpu']
            lines.append(('TEMP', f'{temp:.0f}°C', self.config.text_color))
        
        if not lines:
            return result
        
        # Calculer la taille du bloc de texte
        font = cv2.FONT_HERSHEY_SIMPLEX
        line_height = 25
        padding = 10
        total_height = len(lines) * line_height + 2 * padding
        max_width = max(cv2.getTextSize(line[0] + ': ' + line[1], font, 
                                        self.config.font_scale, 
                                        self.config.font_thickness)[0][0] 
                       for line in lines) + 2 * padding
        
        # Déterminer la position
        h, w = frame.shape[:2]
        
        if self.config.position == 'top_left':
            x, y = padding, padding + total_height
        elif self.config.position == 'top_right':
            x, y = w - max_width - padding, padding + total_height
        elif self.config.position == 'bottom_left':
            x, y = padding, h - padding
        elif self.config.position == 'bottom_right':
            x, y = w - max_width - padding, h - padding
        else:
            x, y = w - max_width - padding, padding + total_height
        
        # Dessiner le fond semi-transparent
        overlay = result.copy()
        cv2.rectangle(overlay, 
                     (x - padding, y - total_height),
                     (x + max_width, y),
                     self.config.bg_color, -1)
        
        # Appliquer la transparence
        alpha = self.config.bg_alpha
        cv2.addWeighted(overlay, alpha, result, 1 - alpha, 0, result)
        
        # Dessiner le texte
        current_y = y - total_height + line_height
        
        for label, value, color in lines:
            text = f"{label}: {value}"
            cv2.putText(result, text, (x, current_y), 
                       font, self.config.font_scale, color, 
                       self.config.font_thickness, cv2.LINE_AA)
            current_y += line_height
        
        return result
    
    def toggle_enabled(self):
        """Active/désactive l'overlay"""
        self.enabled = not self.enabled
        return self.enabled
    
    def reset(self):
        """Réinitialise les compteurs"""
        self.frame_count = 0
        self.fps_start_time = time.time()
        self.current_fps = 0
        self.metrics.clear()


# Exemple d'utilisation
if __name__ == "__main__":
    print("Test du service System Overlay")
    
    overlay = SystemOverlayService()
    
    # Frame test
    test_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    
    # Simuler quelques frames pour avoir des FPS
    for i in range(30):
        processed = overlay.draw_overlay(test_frame)
        time.sleep(0.03)  # ~33 FPS
    
    print(f"FPS actuel: {overlay.current_fps:.1f}")
    print(f"CPU: {overlay.metrics.get('cpu', 'N/A')}%")
    print(f"RAM: {overlay.metrics.get('ram', {}).get('percent', 'N/A')}%")
