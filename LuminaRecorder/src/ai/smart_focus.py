"""
Smart Focus - Suivi Intelligent de Zone Active

Détecte automatiquement les zones d'intérêt à l'écran :
- Fenêtres actives avec mouvement de souris
- Zones de texte en cours d'édition
- Applications en plein écran
- Détection de changements visuels importants

Adapte dynamiquement la zone d'enregistrement pour optimiser :
- La performance (réduction de la surface à capturer)
- La pertinence (focus sur le contenu important)
- La confidentialité (exclusion des zones sensibles)
"""

import cv2
import numpy as np
import time
from typing import Tuple, Optional, List
from dataclasses import dataclass


@dataclass
class ActiveZone:
    """Représente une zone active détectée"""
    x: int
    y: int
    width: int
    height: int
    confidence: float  # 0.0 à 1.0
    zone_type: str  # 'window', 'text', 'fullscreen', 'motion'
    timestamp: float


class SmartFocusEngine:
    """
    Moteur de Smart Focus pour détection intelligente de zones
    
    Utilise la vision par ordinateur pour :
    1. Détecter les fenêtres actives
    2. Suivre les mouvements de souris
    3. Identifier les zones de texte
    4. Adapter la zone d'enregistrement en temps réel
    """
    
    def __init__(self, sensitivity: float = 0.7):
        """
        Args:
            sensitivity: Seuil de sensibilité (0.0 à 1.0)
                        Plus élevé = détection plus réactive
        """
        self.sensitivity = sensitivity
        self.last_frame = None
        self.active_zones: List[ActiveZone] = []
        self.current_zone: Optional[ActiveZone] = None
        self.motion_threshold = int(255 * (1.0 - sensitivity))
        
        # Paramètres de lissage pour éviter les sauts brusques
        self.smoothing_factor = 0.3
        self.zone_history: List[ActiveZone] = []
        self.max_history = 5
        
    def detect_motion(self, current_frame: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Détecte les zones de mouvement dans l'image
        
        Args:
            current_frame: Image actuelle (BGR ou RGB)
            
        Returns:
            Tuple (x, y, width, height) de la zone de mouvement ou None
        """
        if self.last_frame is None:
            self.last_frame = current_frame.copy()
            return None
            
        # Conversion en niveaux de gris
        if len(current_frame.shape) == 3:
            current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
            last_gray = cv2.cvtColor(self.last_frame, cv2.COLOR_BGR2GRAY)
        else:
            current_gray = current_frame
            last_gray = self.last_frame
            
        # Calcul de la différence
        frame_diff = cv2.absdiff(last_gray, current_gray)
        
        # Seuil de détection
        _, thresh = cv2.threshold(frame_diff, self.motion_threshold, 255, cv2.THRESH_BINARY)
        
        # Dilatation pour connecter les zones proches
        kernel = np.ones((5, 5), np.uint8)
        dilated_thresh = cv2.dilate(thresh, kernel, iterations=2)
        
        # Recherche des contours
        contours, _ = cv2.findContours(dilated_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return None
            
        # Trouver le plus grand contour (mouvement principal)
        largest_contour = max(contours, key=cv2.contourArea)
        
        # Filtrer les petits mouvements (bruit)
        min_area = int(current_frame.shape[0] * current_frame.shape[1] * 0.001)
        if cv2.contourArea(largest_contour) < min_area:
            return None
            
        # Rectangle englobant
        x, y, w, h = cv2.boundingRect(largest_contour)
        
        # Marge autour de la zone de mouvement
        margin = 50
        x = max(0, x - margin)
        y = max(0, y - margin)
        w = min(current_frame.shape[1] - x, w + 2 * margin)
        h = min(current_frame.shape[0] - y, h + 2 * margin)
        
        return (x, y, w, h)
    
    def detect_active_window(self, screen_width: int, screen_height: int) -> Optional[ActiveZone]:
        """
        Simule la détection de fenêtre active
        (À améliorer avec pygetwindow ou win32gui sur Windows)
        
        Args:
            screen_width: Largeur totale de l'écran
            screen_height: Hauteur totale de l'écran
            
        Returns:
            ActiveZone de la fenêtre active ou None
        """
        # Simulation basique - à remplacer par une vraie détection OS
        # Dans une version complète, utiliserait :
        # - Windows: win32gui.GetForegroundWindow() + GetWindowRect()
        # - Linux: Xlib + ewmh
        # - macOS: Quartz + Accessibility API
        
        # Par défaut, retourne l'écran entier comme "fenêtre active"
        return ActiveZone(
            x=0,
            y=0,
            width=screen_width,
            height=screen_height,
            confidence=0.8,
            zone_type='fullscreen',
            timestamp=time.time()
        )
    
    def update(self, current_frame: np.ndarray, screen_width: int, screen_height: int) -> Optional[ActiveZone]:
        """
        Met à jour la détection de zone active
        
        Args:
            current_frame: Image actuelle
            screen_width: Largeur de l'écran
            screen_height: Hauteur de l'écran
            
        Returns:
            ActiveZone recommandée pour l'enregistrement
        """
        # Détection de mouvement
        motion_zone = self.detect_motion(current_frame)
        
        # Détection de fenêtre active
        window_zone = self.detect_active_window(screen_width, screen_height)
        
        # Combinaison des zones détectées
        new_zones: List[ActiveZone] = []
        
        if motion_zone:
            x, y, w, h = motion_zone
            new_zones.append(ActiveZone(
                x=x, y=y, width=w, height=h,
                confidence=0.9,
                zone_type='motion',
                timestamp=time.time()
            ))
        
        if window_zone:
            new_zones.append(window_zone)
        
        self.active_zones = new_zones
        
        # Sélection de la meilleure zone
        if new_zones:
            # Priorité : motion > window > fullscreen
            best_zone = max(new_zones, key=lambda z: (
                2 if z.zone_type == 'motion' else 
                1 if z.zone_type == 'window' else 0,
                z.confidence
            ))
            
            # Lissage temporel
            self.zone_history.append(best_zone)
            if len(self.zone_history) > self.max_history:
                self.zone_history.pop(0)
                
            if len(self.zone_history) >= 3:
                # Moyenne glissante des coordonnées
                avg_x = int(sum(z.x for z in self.zone_history) / len(self.zone_history))
                avg_y = int(sum(z.y for z in self.zone_history) / len(self.zone_history))
                avg_w = int(sum(z.width for z in self.zone_history) / len(self.zone_history))
                avg_h = int(sum(z.height for z in self.zone_history) / len(self.zone_history))
                
                best_zone = ActiveZone(
                    x=avg_x, y=avg_y, width=avg_w, height=avg_h,
                    confidence=best_zone.confidence,
                    zone_type=best_zone.zone_type,
                    timestamp=time.time()
                )
            
            self.current_zone = best_zone
        else:
            # Zone par défaut : écran entier
            self.current_zone = ActiveZone(
                x=0, y=0, width=screen_width, height=screen_height,
                confidence=0.5,
                zone_type='fullscreen',
                timestamp=time.time()
            )
        
        # Mise à jour du frame de référence
        self.last_frame = current_frame.copy()
        
        return self.current_zone
    
    def get_recording_crop(self) -> Optional[Tuple[int, int, int, int]]:
        """
        Retourne les coordonnées de crop pour l'enregistrement
        
        Returns:
            Tuple (x, y, width, height) ou None pour écran entier
        """
        if self.current_zone and self.current_zone.zone_type != 'fullscreen':
            return (
                self.current_zone.x,
                self.current_zone.y,
                self.current_zone.width,
                self.current_zone.height
            )
        return None
    
    def reset(self):
        """Réinitialise le moteur de détection"""
        self.last_frame = None
        self.active_zones = []
        self.current_zone = None
        self.zone_history = []


# Exemple d'utilisation
if __name__ == "__main__":
    print("Test du module Smart Focus")
    engine = SmartFocusEngine(sensitivity=0.7)
    
    # Simulation avec une image test
    test_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    zone = engine.update(test_frame, 1920, 1080)
    
    if zone:
        print(f"Zone détectée: {zone.zone_type} @ ({zone.x}, {zone.y}) {zone.width}x{zone.height}")
        print(f"Confiance: {zone.confidence:.2f}")
    
    crop = engine.get_recording_crop()
    if crop:
        print(f"Crop recommandé: {crop}")
    else:
        print("Écran entier recommandé")
