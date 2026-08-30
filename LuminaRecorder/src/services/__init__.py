"""
Lumina Services - Module de Services Avancés
Version 2.1.0

Contient les services pour :
- Moteur IA Unifié (Ollama, OpenAI, Claude, Gemini, DeepSeek, NVIDIA)
- OCR Temps Réel (reconnaissance de texte)
- Flou Dynamique (Privacy Blur)
- Overlay Système (métriques en direct)
- CLI & Automation (ligne de commande)
"""

__version__ = "2.1.0"
__author__ = "Lumina Team"

from .ai_engine import LuminaAIEngine, LuminaAIService, get_ai_engine_from_config
from .ocr_service import OCRService
from .privacy_blur import PrivacyBlurService
from .system_overlay import SystemOverlayService
from .cli_interface import CLIInterface

__all__ = [
    'LuminaAIEngine',
    'LuminaAIService',
    'get_ai_engine_from_config',
    'OCRService',
    'PrivacyBlurService',
    'SystemOverlayService',
    'CLIInterface'
]
