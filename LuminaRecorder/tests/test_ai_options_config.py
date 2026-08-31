from utils.config_manager import ConfigManager
from ui import main_window
from ui.main_window import AIOptions
from filters.privacy_blur_filter import PrivacyBlurFilter
from filters.clean_canvas_filter import CleanCanvasFilter
from postprocess.subtitles_processor import SubtitlesProcessor
from postprocess.magic_cut_processor import MagicCutProcessor


def make_config(tmp_path):
    return ConfigManager(config_path=str(tmp_path / "test_config.ini"))


def test_load_defaults_all_false(tmp_path):
    cfg = make_config(tmp_path)
    opts = AIOptions.load(cfg)
    assert opts == {'privacy_blur': False, 'clean_canvas': False,
                    'overlay': False, 'subtitles': False,
                    'magic_cut': False}


def test_save_then_load_roundtrip(tmp_path):
    cfg = make_config(tmp_path)
    wanted = {'privacy_blur': True, 'clean_canvas': False,
              'overlay': True, 'subtitles': True, 'magic_cut': False}
    AIOptions.save(cfg, wanted)
    cfg2 = ConfigManager(config_path=str(tmp_path / "test_config.ini"))
    assert AIOptions.load(cfg2) == wanted


def test_build_filters_matches_checked_options():
    opts = {'privacy_blur': False, 'clean_canvas': True,
            'overlay': False, 'subtitles': False, 'magic_cut': False}
    filters = AIOptions.build_filters(opts)
    assert len(filters) == 1
    assert isinstance(filters[0], CleanCanvasFilter)


def test_privacy_blur_filter_added_only_when_ocr_available(monkeypatch):
    opts = {'privacy_blur': True, 'clean_canvas': False,
            'overlay': False, 'subtitles': False, 'magic_cut': False}

    monkeypatch.setattr(main_window, 'ocr_is_available', lambda: True)
    filters = AIOptions.build_filters(opts)
    assert len(filters) == 1
    assert isinstance(filters[0], PrivacyBlurFilter)


def test_privacy_blur_filter_skipped_without_ocr(monkeypatch):
    """Sans moteur OCR le flou n'a aucune zone à masquer : ne pas ajouter
    un filtre inerte, même si le .ini garde privacy_blur = true."""
    opts = {'privacy_blur': True, 'clean_canvas': False,
            'overlay': False, 'subtitles': False, 'magic_cut': False}

    monkeypatch.setattr(main_window, 'ocr_is_available', lambda: False)
    assert AIOptions.build_filters(opts) == []


def test_build_postprocessors_order_subtitles_first():
    opts = {'privacy_blur': False, 'clean_canvas': False,
            'overlay': False, 'subtitles': True, 'magic_cut': True}
    procs = AIOptions.build_postprocessors(opts)
    assert isinstance(procs[0], SubtitlesProcessor)
    assert isinstance(procs[1], MagicCutProcessor)


def test_parse_max_silence_values():
    assert AIOptions.parse_max_silence("3 s") == 3.0
    assert AIOptions.parse_max_silence("30 s") == 30.0
    assert AIOptions.parse_max_silence("1 s") == 1.0
    assert AIOptions.parse_max_silence("Tous") == float('inf')
    assert AIOptions.parse_max_silence("") == float('inf')
    assert AIOptions.parse_max_silence("bizarre") == 3.0


def test_magic_cut_threshold_reaches_processor():
    """Le seuil choisi dans l'interface doit atteindre le processeur :
    à 3 s les temps de navigation sont protégés, à 30 s ils sont coupés."""
    opts = {'privacy_blur': False, 'clean_canvas': False, 'overlay': False,
            'subtitles': False, 'magic_cut': True}

    procs = AIOptions.build_postprocessors(opts, "30 s")
    assert procs[0].max_silence_duration == 30.0

    procs = AIOptions.build_postprocessors(opts, "Tous")
    assert procs[0].max_silence_duration == float('inf')

    procs = AIOptions.build_postprocessors(opts)
    assert procs[0].max_silence_duration == 3.0
