"""Tests du pont entre l'interface web et le moteur.

Le pont reçoit ses dépendances par injection : ces tests le pilotent avec
de faux moteurs, sans ouvrir de fenêtre ni enregistrer quoi que ce soit.
"""

import threading
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


class FakeWebcam:
    """Source webcam factice : image immédiate, ou erreur à la demande."""
    instances = []

    def __init__(self, device_index=0, erreur="", **kwargs):
        import numpy as np
        FakeWebcam.instances.append(self)
        self.device_index = device_index
        self._erreur = erreur
        self.demarree = False
        self.arretee = False
        self.image = None if erreur else np.zeros((480, 640, 3), np.uint8)

    def start(self):
        self.demarree = True

    def latest(self):
        return None if self.arretee else self.image

    @property
    def prete(self):
        return self.latest() is not None

    @property
    def erreur(self):
        return self._erreur

    def stop(self):
        self.arretee = True


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
    b._window = FakeWindow()
    FakeWebcam.instances.clear()
    b._webcam_factory = FakeWebcam
    b._lister_webcams = lambda rafraichir=False: [
        {'index': 0, 'nom': "Cam de test"}]
    yield b
    # Remise au repos AVANT shutdown : les boucles du décompte, de la
    # minuterie et de l'aperçu sortent toutes sur l'état. Sans cela, un
    # test qui se termine en PENDING laisse son décompte arriver à terme
    # après coup — _launch() démarre alors une capture hors test, qui
    # lance à son tour une minuterie et un aperçu que plus rien
    # n'arrête. Ces threads tournent jusqu'à la fin de la session, sur
    # des time.sleep redevenus réels une fois le monkeypatch défait :
    # d'où des exécutions de la suite plusieurs fois plus longues.
    b.state = IDLE
    b.shutdown()


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


def test_encodage_recoit_le_fps_nominal(bridge, monkeypatch):
    """Le flux brut est à cadence constante nominale, chaque image tenue
    à sa place réelle : c'est cette cadence que FFmpeg doit lire.

    L'ancien contrat encodait la cadence MESURÉE arrondie. Mesuré sur un
    enregistrement réel : 17,47 im/s arrondis à 17 étiraient la vidéo de
    2,8 %, et surtout la cadence variable de la capture (11 à 20 im/s)
    faisait dériver l'image de 6,6 s en 44 s."""
    demarrer_sans_attendre(bridge, monkeypatch)
    bridge.recorder.fps = 25
    bridge.recorder.actual_fps = 11.4
    bridge.stop_recording()

    assert attendre(lambda: FakeEncoder.instances
                    and FakeEncoder.instances[-1].calls)
    assert FakeEncoder.instances[-1].calls[0]['fps'] == 25


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

    assert bridge._window.events_named('state')


def test_une_page_fermee_ne_casse_pas_le_traitement(bridge):
    """Un échec d'affichage ne doit jamais interrompre un enregistrement."""
    class FenetreMorte:
        def evaluate_js(self, script):
            raise RuntimeError("fenêtre détruite")
    bridge._window = FenetreMorte()

    bridge.emit('state', 'recording')     # ne doit pas lever
    assert bridge.start_recording()['ok'] is True


def test_emit_sans_fenetre_ne_leve_pas(bridge):
    bridge._window = None

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

    envoyes = bridge._window.events_named('countdown')
    # 3, 2, 1 puis 0 : le dernier chiffre ne doit pas sauter
    assert len(envoyes) == 4


def test_annulation_pendant_le_decompte_ne_capture_rien(bridge):
    bridge.start_recording()

    result = bridge.stop_recording()

    assert result['cancelled'] is True
    assert bridge.state == IDLE
    assert bridge.recorder.started_with is None


def test_la_fermeture_pendant_le_decompte_n_ouvre_aucune_capture(bridge,
                                                                  monkeypatch):
    """Fermer la fenêtre pendant le décompte ne doit pas laisser le
    thread survivant lancer une capture sans fenêtre : sans la remise à
    IDLE dans shutdown(), _countdown() voit encore PENDING et appelle
    _launch(), qui démarre des boucles de minuterie et d'aperçu que plus
    rien n'arrête."""
    monkeypatch.setattr(bridge, 'COUNTDOWN_SECONDS', 1, raising=False)

    bridge.start_recording()
    bridge.shutdown()

    time.sleep(1.5)   # laisse le décompte, non annulé, aller à son terme
    assert bridge.recorder.started_with is None
    assert bridge.state == IDLE


def test_tailles_de_la_capsule_et_du_widget():
    assert LuminaBridge.CAPSULE_SIZE == (440, 352)
    assert LuminaBridge.COMPACT_SIZE == (360, 180)


def test_le_decompte_se_joue_dans_la_capsule_sans_bouger(bridge):
    """Le décompte reste là où l'utilisateur a posé sa capsule : rien
    ne saute avant que la capture ne commence."""
    bridge.start_recording()

    assert bridge._window.size is None
    assert bridge._window.on_top is False


def test_l_exclusion_de_capture_est_posee_des_le_decompte(bridge, monkeypatch):
    """Visible pour l'utilisateur, absent de la vidéo. Posée dès le
    décompte pour que la bascule vers le widget soit invisible, levée
    au retour — sinon un autre outil ne pourrait plus filmer Lumina."""
    appels = []
    monkeypatch.setattr(bridge, '_set_capture_affinity', appels.append)

    bridge.start_recording()
    assert appels == [True]

    bridge.stop_recording()          # annulation pendant le décompte
    assert appels == [True, False]


def test_le_widget_remplace_la_capsule_pendant_la_capture(bridge, monkeypatch):
    demarrer_sans_attendre(bridge, monkeypatch)

    assert bridge._window.size == LuminaBridge.COMPACT_SIZE
    assert bridge._window.on_top is True


def test_les_coins_sont_arrondis_apres_chaque_redimensionnement(bridge,
                                                                 monkeypatch):
    rayons = []
    monkeypatch.setattr(bridge, '_arrondir_coins', rayons.append)
    demarrer_sans_attendre(bridge, monkeypatch)
    bridge.stop_recording()
    attendre(lambda: bridge.state == IDLE)

    assert rayons == [22, 28]


def test_arrondir_les_coins_sans_handle_ne_leve_pas(bridge):
    bridge._arrondir_coins(28)       # FakeWindow n'a pas de .native


def test_preparer_la_fenetre_lui_donne_sa_vraie_taille(bridge, monkeypatch):
    """Mesuré : width=440,height=352 à la création donne 424×313 sur une
    fenêtre sans cadre. On corrige une fois la fenêtre ouverte."""
    rayons = []
    monkeypatch.setattr(bridge, '_arrondir_coins', rayons.append)
    bridge.preparer_fenetre()

    assert bridge._window.size == LuminaBridge.CAPSULE_SIZE
    assert rayons == [28]


def test_le_tick_porte_duree_et_taille(bridge, monkeypatch):
    """Le widget affiche la taille du fichier : elle doit accompagner
    chaque battement, pas seulement la durée."""
    demarrer_sans_attendre(bridge, monkeypatch)

    assert attendre(lambda: bridge._window.events_named('tick'))
    envoye = bridge._window.events_named('tick')[0]
    assert '"seconds"' in envoye
    assert '"bytes"' in envoye


def test_taille_nulle_avant_le_demarrage(bridge):
    """Sans horloge de départ, l'estimation vaut zéro : ne pas lever."""
    assert bridge._recorded_bytes() == 0


def test_taille_estimee_sur_le_debit_pas_sur_le_fichier_brut(bridge):
    """Le brut (AVI quasi non compressé) gonfle de plusieurs Mo par
    seconde puis est jeté : l'afficher faisait croire qu'une seconde de
    capture pesait déjà 20 Mo. On affiche ce que pèsera le MP4 final,
    déduit du débit d'encodage."""
    # 2500 kbit/s vidéo + 192 kbit/s audio = 2692 kbit/s -> 336,5 Ko/s
    estime = bridge._recorded_bytes(seconds=60)

    assert estime == int(60 * (2500 + 192) * 1000 / 8)
    # Ordre de grandeur : ~19 Mo pour une minute, pas 200
    assert 15_000_000 < estime < 25_000_000


def test_debit_analyse_avec_suffixes(bridge):
    assert bridge._bitrate_kbps() == 2500.0


# --- géométrie de la fenêtre ---

class FakeWindowGeometry(FakeWindow):
    """Fenêtre déplaçable, pour vérifier la restauration de position."""

    def __init__(self, x=120, y=60, width=440, height=352):
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
    """L'utilisateur avait déplacé sa capsule : la lui rendre collée au
    coin où se tenait le widget est un défaut visible à chaque capture."""
    bridge._window = FakeWindowGeometry(x=120, y=60, width=440, height=352)
    demarrer_sans_attendre(bridge, monkeypatch)

    assert bridge._window.size == LuminaBridge.COMPACT_SIZE

    bridge.stop_recording()
    assert attendre(lambda: bridge.state == IDLE)

    assert (bridge._window.x, bridge._window.y) == (120, 60)
    assert (bridge._window.width, bridge._window.height) == (440, 352)
    assert bridge._window.on_top is False


def test_une_position_jamais_lue_ne_casse_pas_le_retour(bridge, monkeypatch):
    demarrer_sans_attendre(bridge, monkeypatch)
    bridge.stop_recording()

    assert attendre(lambda: bridge.state == IDLE)
    assert bridge._window.size == LuminaBridge.CAPSULE_SIZE


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


# --- Plugins ---

def _info(identifiant="filigrane", nom="Filigrane", erreur=""):
    from plugins.loader import PluginInfo
    return PluginInfo(nom=nom, description="Logo", auteur="moi",
                      version="1.0", api=1, chemin=f"{identifiant}.py",
                      identifiant=identifiant, erreur=erreur)


def test_le_pont_liste_les_plugins(bridge, monkeypatch):
    from webui import bridge as pont
    monkeypatch.setattr(pont, 'lister_plugins', lambda: [_info()])

    liste = bridge.get_plugins()

    assert liste['ok'] is True
    assert liste['plugins'][0]['nom'] == "Filigrane"
    assert liste['plugins'][0]['actif'] is False


def test_activer_un_plugin_le_memorise(bridge, monkeypatch):
    from webui import bridge as pont
    monkeypatch.setattr(pont, 'lister_plugins', lambda: [_info()])

    bridge.set_plugin_actif('filigrane', True)

    assert bridge.get_plugins()['plugins'][0]['actif'] is True


def test_desactiver_un_plugin(bridge, monkeypatch):
    from webui import bridge as pont
    monkeypatch.setattr(pont, 'lister_plugins', lambda: [_info()])
    bridge.set_plugin_actif('filigrane', True)

    bridge.set_plugin_actif('filigrane', False)

    assert bridge.get_plugins()['plugins'][0]['actif'] is False


def test_un_plugin_en_erreur_reste_visible(bridge, monkeypatch):
    """Un plugin refusé doit apparaître AVEC sa raison : disparaître
    sans explication laisserait l'utilisateur sans recours."""
    from webui import bridge as pont
    monkeypatch.setattr(
        pont, 'lister_plugins',
        lambda: [_info('futur', 'Futur', erreur="Version plus récente")])

    p = bridge.get_plugins()['plugins'][0]

    assert p['erreur']
    assert p['actif'] is False


def test_un_plugin_en_erreur_ne_devient_jamais_actif(bridge, monkeypatch):
    """Même activé dans la configuration, un plugin refusé reste
    inactif."""
    from webui import bridge as pont
    monkeypatch.setattr(
        pont, 'lister_plugins',
        lambda: [_info('futur', 'Futur', erreur="Version plus récente")])
    bridge.set_plugin_actif('futur', True)

    assert bridge.get_plugins()['plugins'][0]['actif'] is False


def test_dossier_de_plugins_illisible_ne_leve_pas(bridge, monkeypatch):
    """L'interface doit s'ouvrir même si le dossier pose problème."""
    from webui import bridge as pont

    def casse():
        raise OSError("dossier inaccessible")

    monkeypatch.setattr(pont, 'lister_plugins', casse)

    resultat = bridge.get_plugins()

    assert resultat['ok'] is False
    assert resultat['plugins'] == []


# --- Garde-fou machines peu puissantes ---------------------------------

def test_une_machine_faible_recoit_un_avertissement(bridge):
    """Activer plusieurs filtres sur une machine modeste dégradera la
    capture : le dire avant plutôt que de laisser l'utilisateur
    découvrir un enregistrement saccadé."""
    bridge.recommended = {'resolution': '1280x720', 'fps': 30,
                          'bitrate': '2500k', 'profile': 'ENTRY'}

    avis = bridge.check_charge({'privacy_blur': True, 'clean_canvas': True,
                                'overlay': True})

    assert avis['avertissement']


def test_une_machine_puissante_n_est_pas_avertie(bridge):
    """Un avertissement affiché à tort décrédibilise tous les autres."""
    bridge.recommended = {'resolution': '1920x1080', 'fps': 60,
                          'bitrate': '8000k', 'profile': 'PRO'}

    avis = bridge.check_charge({'privacy_blur': True, 'clean_canvas': True,
                                'overlay': True})

    assert avis['avertissement'] == ""


def test_un_seul_filtre_ne_declenche_pas_l_avertissement(bridge):
    bridge.recommended = {'profile': 'ENTRY'}

    avis = bridge.check_charge({'privacy_blur': True})

    assert avis['avertissement'] == ""


def test_le_profil_est_lu_sous_la_cle_reelle(bridge):
    """SystemAnalyzer expose « profile », pas « profil ».

    Une faute de frappe ici rendrait le garde-fou muet en permanence,
    sans qu'aucune erreur ne le signale.
    """
    from core.system_analyzer import SystemAnalyzer

    reglages = SystemAnalyzer().get_recommended_settings()

    assert 'profile' in reglages
    bridge.recommended = dict(reglages, profile='ENTRY')
    avis = bridge.check_charge({'privacy_blur': True, 'overlay': True})
    assert avis['avertissement']


def test_profil_inconnu_n_avertit_pas(bridge):
    """L'analyse matérielle peut échouer : le repli ne pose aucun profil.

    Sans profil connu, on ne peut rien affirmer sur la machine — mieux
    vaut se taire que d'alarmer à tort.
    """
    bridge.recommended = {'resolution': '1280x720', 'fps': 30,
                          'bitrate': '2500k'}

    avis = bridge.check_charge({'privacy_blur': True, 'clean_canvas': True,
                                'overlay': True})

    assert avis['avertissement'] == ""


def test_les_plugins_actifs_comptent_dans_la_charge(bridge, monkeypatch):
    """Un plugin tiers coûte autant qu'un filtre natif.

    Ne compter que les filtres natifs sous-estimerait la charge d'un
    utilisateur qui a activé plusieurs plugins.
    """
    bridge.recommended = {'profile': 'ENTRY'}
    monkeypatch.setattr(bridge, '_plugins_actifs',
                        lambda: ['filigrane', 'horodatage'])

    avis = bridge.check_charge({'privacy_blur': True})

    assert avis['avertissement']


# --- Extensions installables -------------------------------------------

def test_le_pont_expose_le_catalogue_des_extensions(bridge):
    """Le panneau doit pouvoir proposer l'installation.

    Sans cela, un utilisateur venant de 1.3.0 voit sa fonctionnalité
    disparaître derrière une case grisée, sans recours.
    """
    resultat = bridge.get_extensions()

    assert resultat['ok'] is True
    cles = {e['cle'] for e in resultat['extensions']}
    assert {'sous_titres', 'ocr'} <= cles
    for ext in resultat['extensions']:
        assert ext['nom']
        assert ext['taille_mo'] > 0
        assert 'installee' in ext


def test_une_extension_inconnue_est_refusee_par_le_pont(bridge):
    resultat = bridge.install_extension('nimporte_quoi')

    assert resultat['ok'] is False
    assert resultat['error']


def test_l_echec_d_installation_ne_leve_pas(bridge, monkeypatch):
    """Une exception ici remonterait jusqu'à l'interface web."""
    import services.extension_installer as ei

    def explose(*a, **k):
        raise RuntimeError("disque plein")

    monkeypatch.setattr(ei, 'installer_extension', explose)

    resultat = bridge.install_extension('sous_titres')

    assert resultat['ok'] is False
    assert resultat['error']


# --- webcam ---

def activer_webcam(bridge):
    bridge.config.set('webcam', 'enabled', True)


def test_l_etat_initial_decrit_la_webcam(bridge):
    etat = bridge.get_initial_state()['webcam']
    assert set(etat) == {'enabled', 'device', 'forme', 'coin', 'taille',
                         'miroir', 'available', 'devices'}
    assert etat['enabled'] is False
    assert etat['available'] is True
    assert etat['devices'] == [{'index': 0, 'nom': "Cam de test"}]


def test_sans_camera_la_webcam_est_indisponible(bridge):
    bridge._lister_webcams = lambda rafraichir=False: []
    assert bridge.get_initial_state()['webcam']['available'] is False


def test_les_reglages_webcam_sont_persistes(bridge):
    for cle, valeur, ini in (('webcam_enabled', True, 'enabled'),
                             ('webcam_device', 1, 'device'),
                             ('webcam_forme', 'carre', 'forme'),
                             ('webcam_coin', 'haut-gauche', 'coin'),
                             ('webcam_taille', 'grande', 'taille'),
                             ('webcam_miroir', False, 'miroir')):
        assert bridge.set_option(cle, valeur)['ok'] is True
        assert ('webcam', ini, valeur) in bridge.config.saved


def test_webcam_desactivee_aucune_source_n_est_creee(bridge, monkeypatch):
    demarrer_sans_attendre(bridge, monkeypatch)
    assert FakeWebcam.instances == []
    filtres = bridge.recorder.kwargs['filters']
    assert all(f.name != "Webcam" for f in filtres)


def test_webcam_activee_la_source_est_ouverte_avant_la_capture(bridge,
                                                                 monkeypatch):
    activer_webcam(bridge)
    bridge.config.set('webcam', 'device', 1)
    demarrer_sans_attendre(bridge, monkeypatch)

    assert len(FakeWebcam.instances) == 1
    source = FakeWebcam.instances[0]
    assert source.demarree is True
    assert source.device_index == 1
    # Le filtre webcam est le dernier de la chaîne transmise au moteur
    filtres = bridge.recorder.kwargs['filters']
    assert filtres and filtres[-1].name == "Webcam"
    assert filtres[-1].source is source


def test_la_webcam_est_liberee_a_l_arret(bridge, monkeypatch):
    activer_webcam(bridge)
    demarrer_sans_attendre(bridge, monkeypatch)
    bridge.stop_recording()
    assert attendre(lambda: bridge.state == IDLE)
    assert FakeWebcam.instances[0].arretee is True
    assert bridge._webcam is None


def test_la_webcam_est_liberee_si_le_decompte_est_annule(bridge):
    activer_webcam(bridge)
    bridge.start_recording()
    bridge.stop_recording()
    assert FakeWebcam.instances[0].arretee is True


def test_la_webcam_est_liberee_si_le_moteur_refuse(bridge, monkeypatch):
    activer_webcam(bridge)
    monkeypatch.setattr(FakeRecorder, 'start_recording',
                        lambda self, path: False)
    monkeypatch.setattr(bridge, 'COUNTDOWN_SECONDS', 0, raising=False)
    monkeypatch.setattr(bridge_module.time, 'sleep', lambda s: None)
    bridge.start_recording()
    assert attendre(lambda: bridge.state == IDLE)
    assert FakeWebcam.instances[0].arretee is True


def test_la_webcam_est_liberee_si_la_preparation_echoue(bridge, monkeypatch):
    """La caméra est ouverte juste avant la construction du moteur : si
    celle-ci lève, elle ne doit pas rester allumée."""
    activer_webcam(bridge)

    def moteur_casse(**kw):
        raise RuntimeError("pas de moteur")
    bridge._recorder_factory = moteur_casse

    assert bridge.start_recording()['ok'] is False
    assert bridge.state == IDLE
    assert FakeWebcam.instances[0].arretee is True
    assert bridge._webcam is None


def test_la_webcam_est_liberee_a_la_fermeture(bridge, monkeypatch):
    activer_webcam(bridge)
    demarrer_sans_attendre(bridge, monkeypatch)
    bridge.shutdown()
    assert FakeWebcam.instances[0].arretee is True


def test_une_webcam_en_erreur_n_empeche_pas_d_enregistrer(bridge,
                                                          monkeypatch):
    activer_webcam(bridge)
    bridge._webcam_factory = lambda **kw: FakeWebcam(erreur="occupée", **kw)
    demarrer_sans_attendre(bridge, monkeypatch)

    assert bridge.state == RECORDING
    # L'avis est émis après le passage à RECORDING : attendre plutôt que
    # de lire les événements dans la foulée du changement d'état
    assert attendre(lambda: any('Webcam indisponible' in a for a in
                                bridge._window.events_named('notice')))


def test_une_fabrique_qui_leve_n_empeche_pas_d_enregistrer(bridge,
                                                           monkeypatch):
    activer_webcam(bridge)

    def cassee(**kw):
        raise RuntimeError("pas de pilote")
    bridge._webcam_factory = cassee
    demarrer_sans_attendre(bridge, monkeypatch)

    assert bridge.state == RECORDING
    assert bridge._webcam is None


def test_l_apercu_est_pousse_pendant_l_enregistrement(bridge, monkeypatch):
    activer_webcam(bridge)
    demarrer_sans_attendre(bridge, monkeypatch)
    assert attendre(lambda: bridge._window.events_named('webcam_preview'))
    envoye = bridge._window.events_named('webcam_preview')[0]
    assert '"image"' in envoye
    bridge.stop_recording()
    attendre(lambda: bridge.state == IDLE)
    combien = len(bridge._window.events_named('webcam_preview'))
    time.sleep(0.3)
    # Plus rien après l'arrêt
    assert len(bridge._window.events_named('webcam_preview')) == combien


def test_aucun_apercu_sans_webcam(bridge, monkeypatch):
    demarrer_sans_attendre(bridge, monkeypatch)
    time.sleep(0.3)
    assert bridge._window.events_named('webcam_preview') == []


def test_une_webcam_perdue_est_signalee_une_seule_fois(bridge, monkeypatch):
    activer_webcam(bridge)
    demarrer_sans_attendre(bridge, monkeypatch)
    source = FakeWebcam.instances[0]
    source.image = None
    source._erreur = "Webcam perdue en cours d'enregistrement"
    assert attendre(lambda: any('perdue' in a for a in
                                bridge._window.events_named('notice')))
    time.sleep(0.4)
    assert sum('perdue' in a for a in
               bridge._window.events_named('notice')) == 1
    assert bridge.state == RECORDING


def test_l_avis_de_perte_ne_deborde_pas_sur_l_enregistrement_suivant(
        bridge, monkeypatch):
    """L'aperçu de la session précédente peut être encore en train de
    finir quand la suivante démarre : il ne doit pas émettre l'avis de
    perte à la place — une seule fois pour la session concernée, aucune
    pour la seconde dont la caméra va bien."""
    activer_webcam(bridge)
    demarrer_sans_attendre(bridge, monkeypatch)
    perdue = FakeWebcam.instances[0]
    perdue.image = None
    perdue._erreur = "Webcam perdue en cours d'enregistrement"
    assert attendre(lambda: any('perdue' in a for a in
                                bridge._window.events_named('notice')))

    bridge.stop_recording()
    assert attendre(lambda: bridge.state == IDLE)
    demarrer_sans_attendre(bridge, monkeypatch)
    assert bridge.state == RECORDING
    assert len(FakeWebcam.instances) == 2
    # La deuxième caméra va bien : l'aperçu doit repartir
    assert attendre(lambda: len(bridge._window.events_named(
        'webcam_preview')) > 0)
    time.sleep(0.4)

    assert sum('perdue' in a for a in
               bridge._window.events_named('notice')) == 1


def test_test_webcam_refuse_pendant_le_decompte(bridge):
    """Pendant le décompte la caméra appartient à l'enregistrement."""
    bridge.start_recording()
    assert bridge.state == PENDING

    resultat = bridge.test_webcam(0)

    assert resultat['ok'] is False
    assert 'occupée' in resultat['error']


def test_test_webcam_refuse_si_un_enregistrement_s_intercale(bridge):
    """Le raccourci global lance l'enregistrement depuis son propre
    thread : il peut passer entre la vérification d'état de test_webcam
    et l'ouverture de la caméra. La seconde source ne serait suivie par
    aucun _fermer_webcam et garderait la LED allumée. Ici on simule
    l'entrelacement en tenant le verrou pendant que l'enregistrement
    démarre : test_webcam doit revérifier l'état une fois le verrou
    obtenu, et refuser."""
    activer_webcam(bridge)
    bridge._webcam_lock.acquire()
    try:
        resultat = {}
        essai = threading.Thread(
            target=lambda: resultat.update(bridge.test_webcam(0)))
        essai.start()
        # Le thread a passé la première vérification d'état et attend
        # maintenant le verrou : l'enregistrement s'intercale ici
        time.sleep(0.1)
        assert essai.is_alive()
        bridge.state = PENDING
    finally:
        bridge._webcam_lock.release()
    essai.join(timeout=3.0)

    assert resultat.get('ok') is False
    assert 'occupée' in resultat['error']
    # Aucune source n'a été ouverte hors du suivi du pont
    assert FakeWebcam.instances == []


def test_get_webcams_relit_la_liste(bridge):
    appels = []
    bridge._lister_webcams = lambda rafraichir=False: appels.append(
        rafraichir) or [{'index': 0, 'nom': "Cam"}]
    resultat = bridge.get_webcams()
    assert resultat == {'ok': True, 'webcams': [{'index': 0, 'nom': "Cam"}]}
    assert appels == [True]


def test_test_webcam_rend_une_image(bridge):
    resultat = bridge.test_webcam(0)
    assert resultat['ok'] is True
    assert isinstance(resultat['image'], str) and len(resultat['image']) > 100
    assert FakeWebcam.instances[0].arretee is True


def test_test_webcam_signale_l_erreur(bridge):
    bridge._webcam_factory = lambda **kw: FakeWebcam(erreur="occupée", **kw)
    resultat = bridge.test_webcam(0)
    assert resultat['ok'] is False
    assert 'occupée' in resultat['error']


def test_test_webcam_refuse_pendant_l_enregistrement(bridge, monkeypatch):
    demarrer_sans_attendre(bridge, monkeypatch)
    resultat = bridge.test_webcam(0)
    assert resultat['ok'] is False
