"""
Privacy Blur Service - Flou Dynamique pour Confidentialité

Applique automatiquement un flou sur :
- Zones détectées comme sensibles par OCR
- Fenêtres spécifiées par l'utilisateur
- Régions prédéfinies (coins d'écran, barres)
- Informations personnelles détectées

Types de flou disponibles :
- Gaussien (doux, naturel)
- Pixelisé (style censure)
- Masque noir (caché complètement)
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass


@dataclass
class BlurRegion:
    """Région à flouter"""
    x: int
    y: int
    width: int
    height: int
    blur_type: str  # 'gaussian', 'pixelate', 'black'
    blur_strength: int  # 1-50
    reason: str  # 'sensitive', 'manual', 'auto'
    permanent: bool = True


class PrivacyBlurService:
    """
    Service de floutage dynamique pour protection de vie privée
    
    Fonctionnalités :
    - Flou gaussien configurable
    - Pixelisation style censure
    - Détection automatique via OCR
    - Zones manuelles persistantes
    """
    
    def __init__(self):
        self.blur_regions: List[BlurRegion] = []
        self.default_blur_type = 'gaussian'
        self.default_strength = 25
        self.enabled = True
    
    def add_blur_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        blur_type: str = 'gaussian',
        strength: int = 25,
        reason: str = 'manual',
        permanent: bool = True
    ):
        """
        Ajoute une région à flouter
        
        Args:
            x, y: Coordonnées du coin supérieur gauche
            width, height: Dimensions de la région
            blur_type: 'gaussian', 'pixelate', ou 'black'
            strength: Force du flou (1-50)
            reason: Raison du floutage
            permanent: Si True, persiste entre les frames
        """
        region = BlurRegion(
            x=x, y=y, width=width, height=height,
            blur_type=blur_type,
            blur_strength=min(50, max(1, strength)),
            reason=reason,
            permanent=permanent
        )
        self.blur_regions.append(region)
        print(f"✓ Région flou ajoutée: {reason} @ ({x},{y}) {width}x{height}")
    
    def remove_blur_region(self, x: int, y: int) -> bool:
        """Supprime une région de flou par coordonnées"""
        for i, region in enumerate(self.blur_regions):
            if abs(region.x - x) < 10 and abs(region.y - y) < 10:
                self.blur_regions.pop(i)
                print(f"✓ Région flou supprimée @ ({x},{y})")
                return True
        return False
    
    def apply_gaussian_blur(self, frame: np.ndarray, region: BlurRegion) -> np.ndarray:
        """Applique un flou gaussien"""
        result = frame.copy()
        
        x, y, w, h = region.x, region.y, region.width, region.height
        
        # Vérifier limites
        x = max(0, x)
        y = max(0, y)
        w = min(frame.shape[1] - x, w)
        h = min(frame.shape[0] - y, h)
        
        if w <= 0 or h <= 0:
            return result
        
        # Taille du kernel doit être impaire
        kernel_size = region.blur_strength * 2 + 1
        if kernel_size % 2 == 0:
            kernel_size += 1
        
        roi = result[y:y+h, x:x+w]
        blurred = cv2.GaussianBlur(roi, (kernel_size, kernel_size), 0)
        result[y:y+h, x:x+w] = blurred
        
        return result
    
    def apply_pixelate_blur(self, frame: np.ndarray, region: BlurRegion) -> np.ndarray:
        """Applique un effet de pixelisation"""
        result = frame.copy()
        
        x, y, w, h = region.x, region.y, region.width, region.height
        
        x = max(0, x)
        y = max(0, y)
        w = min(frame.shape[1] - x, w)
        h = min(frame.shape[0] - y, h)
        
        if w <= 0 or h <= 0:
            return result
        
        # Facteur de pixelisation
        pixel_factor = max(2, region.blur_strength // 3)
        
        roi = result[y:y+h, x:x+w]
        
        # Réduire la taille
        small = cv2.resize(roi, (w // pixel_factor, h // pixel_factor), 
                          interpolation=cv2.INTER_LINEAR)
        
        # Agrandir à nouveau
        pixelated = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        
        result[y:y+h, x:x+w] = pixelated
        
        return result
    
    def apply_black_mask(self, frame: np.ndarray, region: BlurRegion) -> np.ndarray:
        """Applique un masque noir"""
        result = frame.copy()
        
        x, y, w, h = region.x, region.y, region.width, region.height
        
        x = max(0, x)
        y = max(0, y)
        w = min(frame.shape[1] - x, w)
        h = min(frame.shape[0] - y, h)
        
        if w <= 0 or h <= 0:
            return result
        
        result[y:y+h, x:x+w] = 0
        
        return result
    
    def apply_blur(self, frame: np.ndarray, region: BlurRegion) -> np.ndarray:
        """Applique le type de flou spécifié"""
        if region.blur_type == 'gaussian':
            return self.apply_gaussian_blur(frame, region)
        elif region.blur_type == 'pixelate':
            return self.apply_pixelate_blur(frame, region)
        elif region.blur_type == 'black':
            return self.apply_black_mask(frame, region)
        else:
            return self.apply_gaussian_blur(frame, region)
    
    def process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Traite une frame en appliquant tous les flous
        
        Args:
            frame: Image à traiter
            
        Returns:
            Image avec les régions floutées
        """
        if not self.enabled:
            return frame
        
        result = frame.copy()
        
        # Appliquer chaque région de flou
        for region in self.blur_regions:
            result = self.apply_blur(result, region)
        
        return result
    
    def auto_detect_from_ocr(self, ocr_regions: list) -> int:
        """
        Détecte automatiquement les zones à flouter depuis les résultats OCR
        
        Args:
            ocr_regions: Liste de TextRegion depuis OCRService
            
        Returns:
            Nombre de régions ajoutées
        """
        added_count = 0
        
        sensitive_keywords = [
            'password', 'mot de passe', 'passwd', 'mdp',
            'secret', 'privé', 'confidentiel',
            'email', 'courriel', '@'
        ]
        
        for region in ocr_regions:
            text_lower = region.text.lower()
            
            # Vérifier si le texte contient des mots sensibles
            is_sensitive = any(keyword in text_lower for keyword in sensitive_keywords)
            
            if is_sensitive:
                # Ajouter une zone de flou autour du texte
                margin = 10
                self.add_blur_region(
                    x=max(0, region.x - margin),
                    y=max(0, region.y - margin),
                    width=region.width + 2 * margin,
                    height=region.height + 2 * margin,
                    blur_type='gaussian',
                    strength=30,
                    reason='sensitive_ocr',
                    permanent=False  # Temporaire, sera réévalué
                )
                added_count += 1
        
        return added_count
    
    def clear_temporary_regions(self):
        """Supprime toutes les régions temporaires"""
        self.blur_regions = [r for r in self.blur_regions if r.permanent]
        print(f"✓ {len(self.blur_regions)} régions permanentes conservées")
    
    def get_region_count(self) -> int:
        """Retourne le nombre de régions actives"""
        return len(self.blur_regions)
    
    def reset(self):
        """Réinitialise toutes les régions"""
        self.blur_regions.clear()
    
    def toggle_enabled(self):
        """Active/désactive le service"""
        self.enabled = not self.enabled
        return self.enabled


# Exemple d'utilisation
if __name__ == "__main__":
    print("Test du service Privacy Blur")
    
    blur_service = PrivacyBlurService()
    
    # Ajouter des régions manuelles
    blur_service.add_blur_region(100, 100, 200, 50, 'gaussian', 25, 'test')
    blur_service.add_blur_region(500, 300, 150, 40, 'pixelate', 15, 'test2')
    
    # Frame test
    test_frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
    
    processed = blur_service.process_frame(test_frame)
    
    print(f"\nRégions actives: {blur_service.get_region_count()}")
    print(f"Frame originale: {test_frame.shape}")
    print(f"Frame traitée: {processed.shape}")
