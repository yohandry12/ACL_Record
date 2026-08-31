"""Tests du pont entre l'interface web et le moteur.

Le pont reçoit ses dépendances par injection : ces tests le pilotent avec
de faux moteurs, sans ouvrir de fenêtre ni enregistrer quoi que ce soit.
"""

import time

import pytest

from webui import bridge as bridge_module
from webui.bridge import IDLE, PENDING, PROCESSING, RECORDING, LuminaBridge


class FakeConfig:
    """ConfigManager minimal, en mémoire."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self.saved = []

    def get(self, section, key, fallback=None):
        return self.values.get((section, key), fallback)

    def get_bool(self, section, key, fallback=False):
        return bool(self.values.get((section, key), fallback))

    def get_int(self, section, key, fallback=0):
        return int(self.values.get((section, key), fallback))

    def get_float(self, section, key, fallback=0.0):
        return float(self.values.get((section, key), fallback))

    def set(self, section, key, value):
        self.values[(section, key)] = value
        self.saved.append((section, key, value))


class FakeRecorder:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.is_recording = False
        self.actual_fps = 30.0
        self.system_audio_path = ""
        self.started_with = None

    def start_recording(self, path):
        self.started_with = path
        self.is_recording = True
        return True

    def stop_recording(self):
        self.is_recording = False
        return ("brut.avi", "brut.wav")


class FakeEncoder:
    instances = []

    def __init__(self):
        FakeEncoder.instances.append(self)
        self.calls = []

    def encode(self, **kwargs):
        self.calls.append(kwargs)
        return True


class FakeWindow:
    """Capture ce que le pont enverrait à la page."""

    def __init__(self):
        self.calls = []
        self.size = None
        self.on_top = False

    def evaluate_js(self, script):
        self.calls.append(script)

    def resize(self, width, height):
        self.size = (width, height)

    def move(self, x, y):
        self.position = (x, y)

    def events_named(self, name):
        return [c for c in self.calls if f'"event": "{name}"' in c]


class FakeAnalyzer:
    class profile:
        value = "TEST"

    def get_recommended_settings(self):
        return {'resolution': '1280x720', 'fps': 30, 'bitrate': '2500k'}


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    FakeEncoder.instances.clear()
    # Aucun fichier temporaire réel ne doit être touché
    monkeypatch.setattr(bridge_module, 'get_temp_dir', lambda: tmp_path)
    b = LuminaBridge(config=FakeConfig({('output', 'save_directory'):
                                        str(tmp_path)}),
                     recorder_factory=FakeRecorder,
                     encoder_factory=FakeEncoder,
                     analyzer=FakeAnalyzer())
    b.window = FakeWindow()
    return b


def attendre(condition, timeout=3.0):
    """Attend qu'une condition threadée devienne vraie."""
    fin = time.time() + timeout
    while time.time() < fin:
        if condition():
            return True
        time.sleep(0.02)
    return False


# --- état initial ---

def test_etat_initial_est_serialisable(bridge):
    import json

    state = bridge.get_initial_state()

    json.dumps(state)   # doit passer : la page le reçoit en JSON
    assert state['state'] == IDLE
    assert 'audio' in state and 'ai' in state


def test_etat_initial_annonce_ce_qui_est_installe(bridge):
    """La page grise les cases dont le moteur est absent : elle doit
    connaître la disponibilité réelle, jamais une valeur inventée."""
    state = bridge.get_initial_state()

    assert {'subtitles', 'privacy_blur', 'summary',
            'subtitle_fix'} <= set(state['ai']['available'])
    for value in state['ai']['available'].values():
        assert isinstance(value, bool)


# --- réglages ---

def test_reglage_simple_est_persiste(bridge):
    result = bridge.set_option('bitrate', '8000k')

    assert result['ok'] is True
    assert bridge.config.get('recording', 'default_bitrate') == '8000k'


def test_option_ia_est_persistee(bridge):
    result = bridge.set_option('magic_cut', True)

    assert result['ok'] is True
    assert bridge.config.get_bool('ai', 'magic_cut') is True


def test_reglage_inconnu_est_refuse_explicitement(bridge):
    """Une clé inconnue doit être signalée, pas ignorée en silence :
    sinon un réglage de la page ne serait jamais appliqué sans qu'on le
    sache."""
    result = bridge.set_option('nimporte_quoi', 1)

    assert result['ok'] is False
    assert 'nimporte_quoi' in result['error']


# --- cycle d'enregistrement ---

def demarrer_sans_attendre(bridge, monkeypatch):
    """Lance la capture en sautant le decompte de 3 s."""
    monkeypatch.setattr(bridge, 'COUNTDOWN_SECONDS', 0, raising=False)
    monkeypatch.setattr(bridge_module.time, 'sleep', lambda s: None)
    bridge.start_recording()
    attendre(lambda: bridge.state == RECORDING)


def test_demarrage_puis_arret(bridge, monkeypatch):
    demarrer_sans_attendre(bridge, monkeypatch)
    assert bridge.state == RECORDING
    assert bridge.recorder.started_with.endswith('.mp4')

    assert bridge.stop_recording()['ok'] is True
    assert attendre(lambda: bridge.state == IDLE)


def test_double_demarrage_refuse(bridge):
    bridge.start_recording()

    second = bridge.start_recording()

    assert second['ok'] is False


def test_arret_sans_enregistrement_refuse(bridge):
    result = bridge.stop_recording()

    assert result['ok'] is False


def test_toggle_alterne_les_etats(bridge, monkeypatch):
    monkeypatch.setattr(bridge, 'COUNTDOWN_SECONDS', 0, raising=False)
    monkeypatch.setattr(bridge_module.time, 'sleep', lambda s: None)
    bridge.toggle_recording()
    assert attendre(lambda: bridge.state == RECORDING)

    bridge.toggle_recording()
    assert attendre(lambda: bridge.state == IDLE)


def test_toggle_ignore_pendant_le_traitement(bridge):
    """Le raccourci global contourne l'interface : il ne doit pas lancer
    un enregistrement par dessus un encodage en cours."""
    bridge.state = PROCESSING

    result = bridge.toggle_recording()

    assert result['ok'] is False
    assert result['busy'] is True
    assert bridge.state == PROCESSING


def test_ffmpeg_absent_empeche_de_demarrer(bridge):
    """Sans FFmpeg, on enregistrerait pour rien et l'échec n'apparaîtrait
    qu'à la fin du traitement."""
    def encoder_manquant():
        raise FileNotFoundError("FFmpeg introuvable")
    bridge._encoder_factory = encoder_manquant

    result = bridge.start_recording()

    assert result['ok'] is False
    assert 'FFmpeg' in result['error']
    assert bridge.state == IDLE


def test_moteur_qui_refuse_revient_au_repos(bridge, monkeypatch):
    class RefuseRecorder(FakeRecorder):
        def start_recording(self, path):
            return False
    bridge._recorder_factory = RefuseRecorder

    demarrer_sans_attendre(bridge, monkeypatch)

    # Le moteur refuse APRES le decompte : on revient au repos
    assert attendre(lambda: bridge.state == IDLE)


def test_encodage_recoit_le_fps_reel(bridge, monkeypatch):
    """Le fps nominal donnerait une vidéo accélérée et désynchronisée du
    son : c'est le fps mesuré qui doit être encodé."""
    demarrer_sans_attendre(bridge, monkeypatch)
    bridge.recorder.actual_fps = 11.4
    bridge.stop_recording()

    assert attendre(lambda: FakeEncoder.instances
                    and FakeEncoder.instances[-1].calls)
    assert FakeEncoder.instances[-1].calls[0]['fps'] == 11


def test_encodage_sans_gain_supplementaire(bridge, monkeypatch):
    """Le gain est déjà appliqué à la capture : le réappliquer ici
    donnerait un son deux fois plus faible."""
    demarrer_sans_attendre(bridge, monkeypatch)
    bridge.stop_recording()

    assert attendre(lambda: FakeEncoder.instances
                    and FakeEncoder.instances[-1].calls)
    assert FakeEncoder.instances[-1].calls[0]['audio_gain'] == 1.0


# --- Smart Focus ---

def test_smart_focus_passe_par_un_etat_d_attente(bridge, monkeypatch):
    monkeypatch.setattr(bridge_module, 'smart_focus_is_available',
                        lambda: True)
    bridge.config.set('recording', 'smart_focus', True)

    result = bridge.start_recording()

    assert result['pending'] is True
    assert bridge.state == PENDING


def test_annulation_pendant_l_attente_ne_capture_rien(bridge, monkeypatch):
    monkeypatch.setattr(bridge_module, 'smart_focus_is_available',
                        lambda: True)
    bridge.config.set('recording', 'smart_focus', True)
    bridge.start_recording()

    result = bridge.stop_recording()

    assert result['cancelled'] is True
    assert bridge.state == IDLE


# --- événements ---

def test_les_changements_d_etat_sont_annonces(bridge):
    bridge.start_recording()

    assert bridge.window.events_named('state')


def test_une_page_fermee_ne_casse_pas_le_traitement(bridge):
    """Un échec d'affichage ne doit jamais interrompre un enregistrement."""
    class FenetreMorte:
        def evaluate_js(self, script):
            raise RuntimeError("fenêtre détruite")
    bridge.window = FenetreMorte()

    bridge.emit('state', 'recording')     # ne doit pas lever
    assert bridge.start_recording()['ok'] is True


def test_emit_sans_fenetre_ne_leve_pas(bridge):
    bridge.window = None

    bridge.emit('tick', 1)


# --- fermeture ---

def test_fermeture_libere_le_raccourci_et_la_capture(bridge):
    class FakeHotkey:
        def __init__(self):
            self.stopped = False
            self.is_active = True
            self.error = ""

        def stop(self):
            self.stopped = True

    bridge.hotkey = FakeHotkey()
    bridge.start_recording()

    bridge.shutdown()

    assert bridge.hotkey.stopped is True
    assert bridge.recorder.is_recording is False


# --- décompte avant capture ---

def test_le_decompte_precede_la_capture(bridge):
    """L'utilisateur doit savoir quand la capture commence : rien n'est
    enregistré tant que le décompte tourne."""
    result = bridge.start_recording()

    assert result['pending'] is True
    assert result['countdown'] == 3
    assert bridge.state == PENDING
    assert bridge.recorder.started_with is None


def test_le_decompte_est_annonce_a_la_page(bridge, monkeypatch):
    monkeypatch.setattr(bridge_module.time, 'sleep', lambda s: None)

    bridge.start_recording()
    attendre(lambda: bridge.state == RECORDING)

    envoyes = bridge.window.events_named('countdown')
    # 3, 2, 1 puis 0 : le dernier chiffre ne doit pas sauter
    assert len(envoyes) == 4


def test_annulation_pendant_le_decompte_ne_capture_rien(bridge):
    bridge.start_recording()

    result = bridge.stop_recording()

    assert result['cancelled'] is True
    assert bridge.state == IDLE
    assert bridge.recorder.started_with is None


def test_le_widget_apparait_des_le_decompte(bridge):
    """Basculer au démarrage exact de la capture ferait sauter la
    fenêtre dans l'enregistrement lui-même."""
    bridge.start_recording()

    assert bridge.window.size == LuminaBridge.COMPACT_SIZE


def test_le_tick_porte_duree_et_taille(bridge, monkeypatch):
    """Le widget affiche la taille du fichier : elle doit accompagner
    chaque battement, pas seulement la durée."""
    demarrer_sans_attendre(bridge, monkeypatch)

    assert attendre(lambda: bridge.window.events_named('tick'))
    envoye = bridge.window.events_named('tick')[0]
    assert '"seconds"' in envoye
    assert '"bytes"' in envoye


def test_taille_nulle_si_le_fichier_n_existe_pas_encore(bridge):
    """À la première seconde, le fichier brut n'est pas encore créé :
    cela ne doit pas lever."""
    bridge.recorder = FakeRecorder()
    bridge.recorder._raw_video_path = "chemin/inexistant.avi"

    assert bridge._recorded_bytes() == 0


# --- géométrie de la fenêtre ---

class FakeWindowGeometry(FakeWindow):
    """Fenêtre déplaçable, pour vérifier la restauration de position."""

    def __init__(self, x=120, y=60, width=900, height=600):
        super().__init__()
        self.x, self.y = x, y
        self.width, self.height = width, height

    def resize(self, width, height):
        self.size = (width, height)
        self.width, self.height = width, height

    def move(self, x, y):
        self.position = (x, y)
        self.x, self.y = x, y


def test_la_fenetre_retrouve_sa_place_apres_enregistrement(bridge,
                                                           monkeypatch):
    """L'utilisateur avait déplacé sa fenêtre : la lui rendre collée au
    coin où se tenait le widget est un défaut visible à chaque capture."""
    bridge.window = FakeWindowGeometry(x=120, y=60, width=900, height=600)
    monkeypatch.setattr(bridge, '_set_native_frame', lambda visible: True)
    demarrer_sans_attendre(bridge, monkeypatch)

    assert bridge.window.size == LuminaBridge.COMPACT_SIZE

    bridge.stop_recording()
    assert attendre(lambda: bridge.state == IDLE)

    assert (bridge.window.x, bridge.window.y) == (120, 60)
    assert (bridge.window.width, bridge.window.height) == (900, 600)


def test_la_bordure_revient_apres_enregistrement(bridge, monkeypatch):
    """Sans bordure, l'utilisateur ne peut plus ni déplacer ni
    redimensionner sa fenêtre."""
    bordures = []
    bridge.window = FakeWindowGeometry()
    monkeypatch.setattr(bridge, '_set_native_frame',
                        lambda visible: bordures.append(visible) or True)
    demarrer_sans_attendre(bridge, monkeypatch)
    bridge.stop_recording()
    attendre(lambda: bridge.state == IDLE)

    assert bordures == [False, True]


def test_une_position_jamais_lue_ne_casse_pas_le_retour(bridge, monkeypatch):
    """Fenêtre pas encore affichée : pas de position à restaurer, mais
    l'enregistrement doit fonctionner quand même."""
    monkeypatch.setattr(bridge, '_set_native_frame', lambda visible: True)
    demarrer_sans_attendre(bridge, monkeypatch)
    bridge.stop_recording()

    assert attendre(lambda: bridge.state == IDLE)


# --- panneau de configuration IA ---

def test_la_config_ia_ne_divulgue_aucune_cle(bridge, monkeypatch):
    """La page reçoit cet objet : une clé en clair y serait lisible par
    tout script qui s'exécute dedans."""
    monkeypatch.setattr(bridge_module, 'providers_status',
                        lambda: [{'id': 'openai', 'has_key': True,
                                  'masked_key': 'sk-abc…7890', 'local': False,
                                  'needs_key': True, 'label': 'OpenAI',
                                  'default_model': 'gpt-4o-mini', 'note': ''}])

    config = bridge.get_ai_config()

    assert 'sk-abcdefghij1234567890' not in repr(config)
    assert config['providers'][0]['masked_key'] == 'sk-abc…7890'


def test_la_config_ia_signale_ce_qui_sort_du_poste(bridge):
    """L'utilisateur doit savoir avant de cocher que le contenu parlé de
    ses enregistrements partira chez un tiers."""
    bridge.config.set('ai', 'provider', 'ollama')
    assert bridge.get_ai_config()['sends_offsite'] is False

    bridge.config.set('ai', 'provider', 'openai')
    assert bridge.get_ai_config()['sends_offsite'] is True


def test_choix_du_fournisseur_persiste(bridge):
    result = bridge.set_ai_provider('claude')

    assert result['ok'] is True
    assert bridge.config.get('ai', 'provider') == 'claude'
    # Un modèle par défaut est posé : sans lui le moteur n'aurait rien
    assert bridge.config.get('ai', 'model')


def test_fournisseur_inconnu_est_refuse(bridge):
    result = bridge.set_ai_provider('service_invente')

    assert result['ok'] is False
    assert bridge.config.get('ai', 'provider') is None


def test_coffre_indisponible_est_signale(bridge, monkeypatch):
    """Ne jamais laisser croire qu'une clé est enregistrée quand elle ne
    l'est pas : l'utilisateur croirait la fonctionnalité active."""
    monkeypatch.setattr(bridge_module, 'set_api_key', lambda p, k: False)

    result = bridge.set_ai_key('openai', 'sk-test')

    assert result['ok'] is False
    assert 'coffre' in result['error'].lower()


def test_la_cle_ne_repart_pas_vers_la_page(bridge, monkeypatch):
    monkeypatch.setattr(bridge_module, 'set_api_key', lambda p, k: True)
    monkeypatch.setattr(bridge_module, 'providers_status', lambda: [])

    result = bridge.set_ai_key('openai', 'sk-secret-a-ne-pas-renvoyer')

    assert 'sk-secret-a-ne-pas-renvoyer' not in repr(result)


def test_test_du_fournisseur_sans_configuration(bridge, monkeypatch):
    monkeypatch.setattr(bridge_module, 'build_engine_from_config',
                        lambda c: None)

    result = bridge.test_ai_provider()

    assert result['ok'] is False


def test_test_du_fournisseur_signale_une_panne(bridge, monkeypatch):
    """Une clé enregistrée peut être invalide : seul un appel réel le
    dit."""
    class MoteurEnPanne:
        def generate_text(self, prompt, system_prompt=None, **kwargs):
            raise RuntimeError("clé refusée")

    monkeypatch.setattr(bridge_module, 'build_engine_from_config',
                        lambda c: MoteurEnPanne())

    result = bridge.test_ai_provider()

    assert result['ok'] is False
    assert 'refusée' in result['error']


def test_test_du_fournisseur_reussi(bridge, monkeypatch):
    class MoteurOk:
        def generate_text(self, prompt, system_prompt=None, **kwargs):
            return "OK"

    monkeypatch.setattr(bridge_module, 'build_engine_from_config',
                        lambda c: MoteurOk())

    result = bridge.test_ai_provider()

    assert result['ok'] is True
    assert result['answer'] == 'OK'


def test_sans_moteur_les_traitements_ia_sont_absents(bridge, monkeypatch):
    """Un post-processeur ajouté sans moteur échouerait au moment de
    s'exécuter, après l'enregistrement : mieux vaut l'omettre."""
    from core.ai_options import AIOptions

    procs = AIOptions.build_postprocessors(
        {'summary': True, 'subtitle_fix': True}, ai_engine=None)

    assert procs == []


def test_avec_moteur_les_traitements_ia_sont_presents():
    from core.ai_options import AIOptions

    procs = AIOptions.build_postprocessors(
        {'subtitles': True, 'summary': True, 'subtitle_fix': True},
        ai_engine=object())

    noms = [type(p).__name__ for p in procs]
    # Les sous-titres produisent le .srt que les deux autres lisent :
    # ils doivent passer en premier
    assert noms[0] == 'SubtitlesProcessor'
    assert 'SummaryProcessor' in noms
    assert 'SubtitleFixProcessor' in noms
