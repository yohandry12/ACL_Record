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

    def evaluate_js(self, script):
        self.calls.append(script)

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

    assert set(state['ai']['available']) == {'subtitles', 'privacy_blur'}
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

def test_demarrage_puis_arret(bridge):
    assert bridge.start_recording()['ok'] is True
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


def test_toggle_alterne_les_etats(bridge):
    bridge.toggle_recording()
    assert bridge.state == RECORDING

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


def test_moteur_qui_refuse_revient_au_repos(bridge):
    class RefuseRecorder(FakeRecorder):
        def start_recording(self, path):
            return False
    bridge._recorder_factory = RefuseRecorder

    result = bridge.start_recording()

    assert result['ok'] is False
    assert bridge.state == IDLE


def test_encodage_recoit_le_fps_reel(bridge):
    """Le fps nominal donnerait une vidéo accélérée et désynchronisée du
    son : c'est le fps mesuré qui doit être encodé."""
    bridge.start_recording()
    bridge.recorder.actual_fps = 11.4
    bridge.stop_recording()

    assert attendre(lambda: FakeEncoder.instances
                    and FakeEncoder.instances[-1].calls)
    assert FakeEncoder.instances[-1].calls[0]['fps'] == 11


def test_encodage_sans_gain_supplementaire(bridge):
    """Le gain est déjà appliqué à la capture : le réappliquer ici
    donnerait un son deux fois plus faible."""
    bridge.start_recording()
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
