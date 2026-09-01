from utils.config_manager import ConfigManager
from core import ai_options
from core.ai_options import AIOptions
from filters.privacy_blur_filter import PrivacyBlurFilter
from filters.clean_canvas_filter import CleanCanvasFilter
from postprocess.subtitles_processor import SubtitlesProcessor
from postprocess.magic_cut_processor import MagicCutProcessor
from postprocess.thumbnail_processor import ThumbnailProcessor


def make_config(tmp_path):
    return ConfigManager(config_path=str(tmp_path / "test_config.ini"))


def test_load_defaults_all_false(tmp_path):
    """Aucune option n'est active tant que l'utilisateur ne l'a pas
    cochée. Vérifié sur toutes les clés déclarées, pour que le test ne
    devienne pas faux au prochain ajout."""
    cfg = make_config(tmp_path)
    opts = AIOptions.load(cfg)
    assert set(opts) == set(AIOptions.KEYS)
    assert all(value is False for value in opts.values())


def test_save_then_load_roundtrip(tmp_path):
    cfg = make_config(tmp_path)
    # Une option sur deux activée, quelle que soit la liste des clés
    wanted = {key: (index % 2 == 0)
              for index, key in enumerate(AIOptions.KEYS)}
    AIOptions.save(cfg, wanted)
    cfg2 = ConfigManager(config_path=str(tmp_path / "test_config.ini"))
    assert AIOptions.load(cfg2) == wanted


def test_build_filters_matches_checked_options():
    opts = {'privacy_blur': False, 'clean_canvas': True,
            'overlay': False, 'subtitles': False, 'magic_cut': False,
            'thumbnails': False}
    filters = AIOptions.build_filters(opts)
    assert len(filters) == 1
    assert isinstance(filters[0], CleanCanvasFilter)


def test_privacy_blur_filter_added_only_when_ocr_available(monkeypatch):
    opts = {'privacy_blur': True, 'clean_canvas': False,
            'overlay': False, 'subtitles': False, 'magic_cut': False,
            'thumbnails': False}

    monkeypatch.setattr(ai_options, 'ocr_is_available', lambda: True)
    filters = AIOptions.build_filters(opts)
    assert len(filters) == 1
    assert isinstance(filters[0], PrivacyBlurFilter)


def test_privacy_blur_filter_skipped_without_ocr(monkeypatch):
    """Sans moteur OCR le flou n'a aucune zone à masquer : ne pas ajouter
    un filtre inerte, même si le .ini garde privacy_blur = true."""
    opts = {'privacy_blur': True, 'clean_canvas': False,
            'overlay': False, 'subtitles': False, 'magic_cut': False,
            'thumbnails': False}

    monkeypatch.setattr(ai_options, 'ocr_is_available', lambda: False)
    assert AIOptions.build_filters(opts) == []


def test_build_postprocessors_order_subtitles_first():
    opts = {'privacy_blur': False, 'clean_canvas': False,
            'overlay': False, 'subtitles': True, 'magic_cut': True,
            'thumbnails': True}
    procs = AIOptions.build_postprocessors(opts)
    assert isinstance(procs[0], SubtitlesProcessor)
    assert isinstance(procs[1], MagicCutProcessor)
    assert isinstance(procs[2], ThumbnailProcessor)


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


# --- Plugins dans la chaîne de filtres ---

def _info_plugin(identifiant="faux", nom="Faux", erreur=""):
    from plugins.loader import PluginInfo
    return PluginInfo(nom=nom, description="", auteur="t", version="1.0",
                      api=1, chemin=f"{identifiant}.py",
                      identifiant=identifiant, erreur=erreur)


def test_les_plugins_actives_rejoignent_la_chaine(monkeypatch):
    """Un plugin activé doit filtrer les images comme un filtre natif."""
    from core import ai_options
    from filters.base import FrameFilter

    class FauxPlugin(FrameFilter):
        name = "Faux"

        def process(self, frame):
            return frame

    monkeypatch.setattr(ai_options, 'lister_plugins',
                        lambda: [_info_plugin()])
    monkeypatch.setattr(ai_options, 'charger_plugin', lambda i: FauxPlugin())

    filtres = AIOptions.build_filters({}, plugins_actifs=['faux'])

    assert any(f.name == "Faux" for f in filtres)


def test_un_plugin_non_active_reste_absent(monkeypatch):
    """Rien ne s'exécute sans décision explicite de l'utilisateur."""
    from core import ai_options

    appels = []
    monkeypatch.setattr(ai_options, 'lister_plugins',
                        lambda: [_info_plugin()])
    monkeypatch.setattr(ai_options, 'charger_plugin',
                        lambda i: appels.append(i))

    AIOptions.build_filters({}, plugins_actifs=[])

    assert appels == []


def test_plugin_defectueux_ne_casse_pas_la_chaine(monkeypatch):
    """Les filtres natifs doivent rester présents malgré un plugin qui
    refuse de se charger."""
    from core import ai_options

    monkeypatch.setattr(ai_options, 'lister_plugins',
                        lambda: [_info_plugin('casse', 'Cassé')])
    monkeypatch.setattr(ai_options, 'charger_plugin', lambda i: None)

    filtres = AIOptions.build_filters({'clean_canvas': True},
                                      plugins_actifs=['casse'])

    assert len(filtres) == 1


def test_un_plugin_en_erreur_n_est_pas_charge(monkeypatch):
    """Un plugin refusé (contrat incompatible) ne doit pas être
    importé, même s'il figure dans la liste des activés."""
    from core import ai_options

    appels = []
    monkeypatch.setattr(
        ai_options, 'lister_plugins',
        lambda: [_info_plugin('futur', 'Futur', erreur="contrat 99")])
    monkeypatch.setattr(ai_options, 'charger_plugin',
                        lambda i: appels.append(i))

    AIOptions.build_filters({}, plugins_actifs=['futur'])

    assert appels == []


def test_un_plugin_qui_n_est_pas_un_filtre_est_ignore(monkeypatch):
    """Un post-traitement activé ne doit pas se retrouver dans la
    chaîne temps réel : les contrats ne sont pas interchangeables."""
    from core import ai_options

    class PasUnFiltre:
        name = "Intrus"

    monkeypatch.setattr(ai_options, 'lister_plugins',
                        lambda: [_info_plugin()])
    monkeypatch.setattr(ai_options, 'charger_plugin',
                        lambda i: PasUnFiltre())

    filtres = AIOptions.build_filters({}, plugins_actifs=['faux'])

    assert filtres == []


def test_sans_plugins_le_comportement_est_inchange():
    """L'appel historique, sans argument de plugins, doit continuer de
    fonctionner à l'identique."""
    filtres = AIOptions.build_filters({'clean_canvas': True})

    assert len(filtres) == 1
