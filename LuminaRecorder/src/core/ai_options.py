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
from filters.base import FrameFilter
from plugins.loader import charger_plugin, lister_plugins
from filters.privacy_blur_filter import PrivacyBlurFilter
from filters.clean_canvas_filter import CleanCanvasFilter
from filters.overlay_filter import OverlayFilter
from postprocess.subtitles_processor import SubtitlesProcessor
from postprocess.magic_cut_processor import MagicCutProcessor
from postprocess.thumbnail_processor import ThumbnailProcessor
from postprocess.ai_text_processors import (SubtitleFixProcessor,
                                            SummaryProcessor)


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
        # Nécessitent un fournisseur IA configuré ET les sous-titres :
        # tous deux travaillent à partir du .srt
        'summary': ('ai', 'summary'),
        'subtitle_fix': ('ai', 'subtitle_fix'),
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
    def build_filters(options: dict, plugins_actifs=None) -> list:
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

        # Plugins de l'utilisateur, APRÈS les filtres natifs : ils
        # travaillent sur une image déjà nettoyée. Un plugin qui refuse
        # de se charger est simplement absent — jamais une exception,
        # sinon un fichier tiers défectueux empêcherait d'enregistrer.
        # Seuls les FrameFilter sont retenus : un post-traitement activé
        # n'a rien à faire dans la chaîne temps réel.
        filters.extend(AIOptions._plugins_filtres(plugins_actifs))
        return filters

    @staticmethod
    def _plugins_filtres(plugins_actifs) -> list:
        """Instancie les plugins activés qui sont des filtres."""
        if not plugins_actifs:
            return []

        try:
            disponibles = {p.identifiant: p for p in lister_plugins()}
        except Exception as e:
            # Un dossier illisible ne doit pas empêcher d'enregistrer
            print(f"[Lumina] Plugins introuvables : {e}")
            return []

        retenus = []
        for identifiant in plugins_actifs:
            info = disponibles.get(identifiant)
            if info is None or not info.utilisable:
                continue
            instance = charger_plugin(info)
            if isinstance(instance, FrameFilter):
                retenus.append(instance)
        return retenus

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
                             delete_original: bool = False,
                             ai_engine=None) -> list:
        """Construit la chaîne de post-traitement, dans l'ordre d'exécution.

        L'ordre n'est pas arbitraire : les sous-titres produisent le .srt
        dont le résumé et la correction ont besoin, et Magic Cut modifie
        la vidéo que les miniatures analysent ensuite.

        `ai_engine` vaut None quand aucun fournisseur IA n'est configuré.
        Les traitements qui en dépendent sont alors simplement absents de
        la chaîne, plutôt qu'ajoutés pour échouer au moment de s'exécuter.
        """
        procs = []
        if options.get('subtitles'):
            procs.append(SubtitlesProcessor())   # produit le .srt

        # Travaillent sur le .srt : juste après les sous-titres, et
        # avant que Magic Cut ne redécoupe la vidéo
        if options.get('subtitle_fix') and ai_engine is not None:
            procs.append(SubtitleFixProcessor(ai_engine))
        if options.get('summary') and ai_engine is not None:
            procs.append(SummaryProcessor(ai_engine))

        if options.get('magic_cut'):
            procs.append(MagicCutProcessor(
                max_silence_duration=AIOptions.parse_max_silence(max_silence),
                delete_original=delete_original))
        if options.get('thumbnails'):
            procs.append(ThumbnailProcessor(ai_engine=ai_engine))
        return procs
