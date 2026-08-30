"""
Lumina Services - Module de Services Avancés
Version 2.0.0

Contient les services pour :
- OCR Temps Réel (reconnaissance de texte)
- Flou Dynamique (Privacy Blur)
- Overlay Système (métriques en direct)
- CLI & Automation (ligne de commande)
"""

__version__ = "2.0.0"
__author__ = "Lumina Team"

from .ocr_service import OCRService
from .privacy_blur import PrivacyBlurService
from .system_overlay import SystemOverlayService
from .cli_interface import CLIInterface

__all__ = [
    'OCRService',
    'PrivacyBlurService',
    'SystemOverlayService',
    'CLIInterface'
]
