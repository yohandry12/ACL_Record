"""
Lumina Recorder - Options IA

Persistance des options IA dans le .ini et construction des filtres
temps réel et des post-processeurs correspondants.

Ce module ne dépend d'aucune bibliothèque d'interface : il est partagé
par l'interface tkinter historique et par l'interface web. Le sortir de
main_window.py évite d'avoir deux copies de cette logique, qui
divergeraient à la première évolution.

Règle du projet appliquée ici : une option cochée dont le moteur est
absent ne produit JAMAIS un filtre inerte. La case correspondante est
grisée dans l'interface, et le .ini peut garder la valeur d'une session
où la dépendance était installée sans que cela ait d'effet.
"""

from utils.config_manager import ConfigManager
from services.ocr_service import ocr_is_available
from filters.privacy_blur_filter import PrivacyBlurFilter
from filters.clean_canvas_filter import CleanCanvasFilter
from filters.overlay_filter import OverlayFilter
from postprocess.subtitles_processor import SubtitlesProcessor
from postprocess.magic_cut_processor import MagicCutProcessor
from postprocess.thumbnail_processor import ThumbnailProcessor


class AIOptions:
    """Logique des Options IA : persistance .ini et construction des
    filtres/post-processeurs. Séparée de la UI pour être testable."""

    # (clé_option) -> (section_ini, clé_ini)
    KEYS = {
        'privacy_blur': ('privacy', 'dynamic_blur'),
        'clean_canvas': ('ai', 'clean_canvas'),
        'overlay': ('system', 'show_overlay'),
        'subtitles': ('ai', 'auto_subtitles'),
        'magic_cut': ('ai', 'magic_cut'),
        'thumbnails': ('ai', 'thumbnails'),
    }

    @staticmethod
    def load(config: ConfigManager) -> dict:
        return {opt: config.get_bool(section, key, fallback=False)
                for opt, (section, key) in AIOptions.KEYS.items()}

    @staticmethod
    def save(config: ConfigManager, options: dict) -> None:
        for opt, (section, key) in AIOptions.KEYS.items():
            config.set(section, key, options.get(opt, False))

    @staticmethod
    def build_filters(options: dict) -> list:
        filters = []
        # Sans moteur OCR, le flou n'a aucune zone à masquer : on n'ajoute
        # pas un filtre inerte, même si le .ini garde la valeur d'une
        # session où easyocr était installé
        if options.get('privacy_blur') and ocr_is_available():
            filters.append(PrivacyBlurFilter())
        if options.get('clean_canvas'):
            filters.append(CleanCanvasFilter())
        if options.get('overlay'):
            filters.append(OverlayFilter())
        return filters

    @staticmethod
    def parse_max_silence(label: str) -> float:
        """"5 s" -> 5.0 ; "Tous" -> aucune limite (tout silence est coupé)."""
        if not label or label.strip().lower() in ('tous', 'tout'):
            return float('inf')
        digits = ''.join(c for c in label if c.isdigit() or c == '.')
        try:
            return float(digits)
        except ValueError:
            return 3.0

    @staticmethod
    def build_postprocessors(options: dict,
                             max_silence: str = "3 s",
                             delete_original: bool = False) -> list:
        procs = []
        if options.get('subtitles'):
            procs.append(SubtitlesProcessor())   # sous-titres AVANT Magic Cut
        if options.get('magic_cut'):
            procs.append(MagicCutProcessor(
                max_silence_duration=AIOptions.parse_max_silence(max_silence),
                delete_original=delete_original))
        if options.get('thumbnails'):
            procs.append(ThumbnailProcessor())   # dernier : agit sur la vidéo finale
        return procs
