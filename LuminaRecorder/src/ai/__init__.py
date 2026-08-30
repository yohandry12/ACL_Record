"""
Lumina AI Module - Intelligence Artificielle
Version 2.0.0

Contient les modules d'IA pour :
- Smart Focus (suivi de zone active)
- Clean Canvas (masquage notifications)
- Whisper Transcription (sous-titres auto)
- Magic Cut (découpage silences)
"""

__version__ = "2.0.0"
__author__ = "Lumina Team"

from .smart_focus import SmartFocusEngine, ActiveZone
from .clean_canvas import CleanCanvasEngine, UIElement
from .magic_cut import MagicCutEngine, SilenceSegment, CutPoint
from .whisper_transcriber import WhisperTranscriber, SubtitleSegment

__all__ = [
    'SmartFocusEngine',
    'ActiveZone',
    'CleanCanvasEngine',
    'UIElement',
    'MagicCutEngine',
    'SilenceSegment',
    'CutPoint',
    'WhisperTranscriber',
    'SubtitleSegment'
]
