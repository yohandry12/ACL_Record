"""
Clean Canvas - Masquage Intelligent des Éléments Indésirables

Détecte et masque automatiquement :
- Notifications système (Windows, applications)
- Barres de tâches indésirables
- Fenêtres sensibles (mots de passe, emails)
- Éléments UI distrayants

Fonctionne en temps réel pendant l'enregistrement pour :
- Améliorer le professionnalisme des vidéos
- Protéger la vie privée
- Réduire les distractions visuelles
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
import time


@dataclass
class UIElement:
    """Représente un élément d'interface détecté"""
    x: int
    y: int
    width: int
    height: int
    element_type: str  # 'notification', 'taskbar', 'popup', 'sensitive'
    confidence: float
    should_hide: bool
    timestamp: float


class CleanCanvasEngine:
    """
    Moteur Clean Canvas pour masquage intelligent
    
    Utilise la vision par ordinateur et des règles heuristiques pour :
    1. Détecter les notifications (coins de l'écran, animations)
    2. Identifier les barres de tâches
    3. Repérer les zones sensibles (champs de mot de passe)
    4. Appliquer des masques ou flous en temps réel
    """
    
    def __init__(self, auto_hide: bool = True):
        """
        Args:
            auto_hide: Masquage automatique activé
        """
        self.auto_hide = auto_hide
        self.detected_elements: List[UIElement] = []
        self.notification_zones: List[Tuple[int, int, int, int]] = []
        self.last_notification_check = 0
        self.notification_cooldown = 2.0  # secondes
        
        # Zones typiques des notifications (Windows)
        # Coin inférieur droit pour les notifications Windows
        self.notification_positions = [
            'bottom_right',  # Windows
            'top_right',     # macOS, certaines apps
            'top_left',      # Certaines notifications Linux
        ]
        
    def detect_taskbar(self, screen_width: int, screen_height: int) -> Optional[UIElement]:
        """
        Détecte la barre des tâches
        
        Args:
            screen_width: Largeur de l'écran
            screen_height: Hauteur de l'écran
            
        Returns:
            UIElement de la barre des tâches ou None
        """
        # Détection basique - position typique de la barre des tâches Windows
        # En production, utiliserait GetWindowRect avec FindWindow("Shell_TrayWnd")
        
        taskbar_height = int(screen_height * 0.05)  # ~5% de la hauteur
        
        return UIElement(
            x=0,
            y=screen_height - taskbar_height,
            width=screen_width,
            height=taskbar_height,
            element_type='taskbar',
            confidence=0.9,
            should_hide=False,  # Par défaut, on garde la taskbar
            timestamp=time.time()
        )
    
    def detect_notifications(self, frame: np.ndarray) -> List[UIElement]:
        """
        Détecte les notifications dans l'image
        
        Args:
            frame: Image actuelle
            
        Returns:
            Liste des UIElement représentant les notifications
        """
        notifications = []
        current_time = time.time()
        
        # Vérifier le cooldown pour éviter trop de détections
        if current_time - self.last_notification_check < self.notification_cooldown:
            return notifications
            
        self.last_notification_check = current_time
        
        height, width = frame.shape[:2]
        
        # Zone de recherche : coin inférieur droit (notifications Windows)
        search_regions = [
            # (x_ratio, y_ratio, w_ratio, h_ratio)
            (0.7, 0.7, 0.3, 0.25),  # Bottom-right
            (0.7, 0.0, 0.3, 0.15),  # Top-right
            (0.0, 0.0, 0.2, 0.1),   # Top-left
        ]
        
        for x_r, y_r, w_r, h_r in search_regions:
            x_start = int(width * x_r)
            y_start = int(height * y_r)
            w_region = int(width * w_r)
            h_region = int(height * h_r)
            
            # Extraire la région d'intérêt
            roi = frame[y_start:y_start+h_region, x_start:x_start+w_region]
            
            if roi.size == 0:
                continue
            
            # Détection basée sur la couleur et le contraste
            # Les notifications ont souvent un fond différent du bureau
            if len(roi.shape) == 3:
                gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            else:
                gray_roi = roi
            
            # Détection de contours pour trouver des rectangles
            edges = cv2.Canny(gray_roi, 50, 150)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for contour in contours:
                area = cv2.contourArea(contour)
                
                # Filtrer par taille (ni trop petit, ni trop grand)
                min_area = int(roi.shape[0] * roi.shape[1] * 0.01)
                max_area = int(roi.shape[0] * roi.shape[1] * 0.8)
                
                if min_area < area < max_area:
                    x, y, w, h = cv2.boundingRect(contour)
                    
                    # Ajuster les coordonnées au cadre global
                    global_x = x_start + x
                    global_y = y_start + y
                    
                    notifications.append(UIElement(
                        x=global_x,
                        y=global_y,
                        width=w,
                        height=h,
                        element_type='notification',
                        confidence=0.75,
                        should_hide=self.auto_hide,
                        timestamp=current_time
                    ))
        
        return notifications
    
    def detect_sensitive_areas(self, frame: np.ndarray) -> List[UIElement]:
        """
        Détecte les zones potentiellement sensibles
        (champs de mot de passe, informations personnelles)
        
        Note: Détection basique, à améliorer avec OCR
        """
        sensitive_areas = []
        
        # Détection basée sur des motifs typiques :
        # - Champs avec étoiles (*****)
        # - Fenêtres avec titre "Password", "Login", etc.
        
        # Pour l'instant, retourne une liste vide
        # Sera implémenté avec le module OCR dans les services
        
        return sensitive_areas
    
    def apply_mask(self, frame: np.ndarray, element: UIElement, blur_strength: int = 15) -> np.ndarray:
        """
        Applique un masque ou un flou sur un élément
        
        Args:
            frame: Image originale
            element: Élément à masquer
            blur_strength: Force du flou (odd number recommandé)
            
        Returns:
            Image avec le masque appliqué
        """
        result = frame.copy()
        
        x, y, w, h = element.x, element.y, element.width, element.height
        
        # Vérifier les limites
        x = max(0, x)
        y = max(0, y)
        w = min(frame.shape[1] - x, w)
        h = min(frame.shape[0] - y, h)
        
        if w <= 0 or h <= 0:
            return result
        
        # Appliquer un flou gaussien
        roi = result[y:y+h, x:x+w]
        
        if blur_strength > 0:
            # S'assurer que blur_strength est impair
            if blur_strength % 2 == 0:
                blur_strength += 1
                
            blurred_roi = cv2.GaussianBlur(roi, (blur_strength, blur_strength), 0)
            result[y:y+h, x:x+w] = blurred_roi
        else:
            # Masque noir simple
            result[y:y+h, x:x+w] = 0
        
        return result
    
    def process_frame(self, frame: np.ndarray, screen_width: int, screen_height: int) -> np.ndarray:
        """
        Traite une image complète pour appliquer Clean Canvas
        
        Args:
            frame: Image à traiter
            screen_width: Largeur de l'écran
            screen_height: Hauteur de l'écran
            
        Returns:
            Image traitée avec les éléments masqués
        """
        if not self.auto_hide:
            return frame
        
        result = frame.copy()
        
        # Détection des notifications
        notifications = self.detect_notifications(frame)
        
        # Détection de la taskbar (optionnelle)
        taskbar = self.detect_taskbar(screen_width, screen_height)
        
        # Détection des zones sensibles
        sensitive = self.detect_sensitive_areas(frame)
        
        # Combiner tous les éléments
        all_elements = notifications + sensitive
        if taskbar and False:  # Désactivé par défaut
            all_elements.append(taskbar)
        
        self.detected_elements = all_elements
        
        # Appliquer les masques
        for element in all_elements:
            if element.should_hide:
                result = self.apply_mask(result, element)
        
        return result
    
    def get_hidden_elements_count(self) -> int:
        """Retourne le nombre d'éléments masqués dans la dernière frame"""
        return sum(1 for e in self.detected_elements if e.should_hide)
    
    def toggle_auto_hide(self):
        """Active/désactive le masquage automatique"""
        self.auto_hide = not self.auto_hide
        return self.auto_hide
    
    def reset(self):
        """Réinitialise le moteur"""
        self.detected_elements = []
        self.notification_zones = []


# Exemple d'utilisation
if __name__ == "__main__":
    print("Test du module Clean Canvas")
    engine = CleanCanvasEngine(auto_hide=True)
    
    # Simulation avec une image test
    test_frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
    
    processed = engine.process_frame(test_frame, 1920, 1080)
    
    hidden_count = engine.get_hidden_elements_count()
    print(f"Éléments masqués: {hidden_count}")
    print(f"Taille frame originale: {test_frame.shape}")
    print(f"Taille frame traitée: {processed.shape}")
