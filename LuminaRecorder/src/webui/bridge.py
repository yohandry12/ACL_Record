"""
Lumina Recorder - Pont entre l'interface web et le moteur

Traduit les appels JavaScript vers le moteur Python existant, et pousse
les changements d'état vers la page. Ne contient aucune logique
d'enregistrement : tout le travail réel appartient à core/, filters/ et
postprocess/.

Deux règles gouvernent ce fichier, apprises des blocages de l'interface
tkinter :

1. Toute opération longue (encodage, post-traitement) part dans un
   thread. Le fil de PyWebView pilote la fenêtre : le bloquer gèle
   l'interface, exactement comme un time.sleep dans une boucle tkinter.

2. Les envois vers la page sont sérialisés par un verrou. Ils viennent de
   plusieurs threads (minuterie, encodage, post-traitement) et
   s'entrelaceraient sinon dans la vue.

Le pont reçoit ses dépendances par injection (`window_factory`,
`recorder_factory`...) : les tests le pilotent avec de faux objets, sans
ouvrir de fenêtre ni enregistrer quoi que ce soit.
"""

import json
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from core.ai_options import AIOptions
from core.encoder import VideoEncoder
from core.focus_tracker import smart_focus_is_available
from core.global_hotkey import DEFAULT_HOTKEY, GlobalHotkey
from core.recorder_core import RecorderCore, get_temp_dir, list_input_devices
from core.system_analyzer import SystemAnalyzer
from core.system_audio import system_audio_is_available
from postprocess.base import run_postprocessors
from postprocess.subtitles_processor import whisper_is_available
from services.ai_credentials import (providers_status, set_api_key,
                                     PROVIDERS)
from services.ai_provider import (DEFAULT_PROVIDER, build_engine,
                                  build_engine_from_config,
                                  sends_data_offsite)
from plugins.loader import lister_plugins, plugins_dir
from services.ocr_service import ocr_is_available
from services.update_checker import check_for_update, download_setup
from utils.config_manager import ConfigManager
from version import __version__ as APP_VERSION


# États possibles de l'application, tels que la page les comprend
IDLE = 'idle'              # prêt, aucun enregistrement
PENDING = 'pending'        # délai de bascule du Smart Focus
RECORDING = 'recording'    # capture en cours
PROCESSING = 'processing'  # encodage et post-traitement


class LuminaBridge:
    """Objet exposé au JavaScript via `js_api`.

    Chaque méthode publique est appelable depuis la page en
    `window.pywebview.api.<nom>(...)`, et renvoie un dictionnaire
    sérialisable. Les exceptions sont attrapées et transformées en
    message lisible : une erreur d'interface ne doit jamais interrompre
    un enregistrement en cours.
    """

    # Widget affiché pendant la capture (voir assets/Records_examples/
    # record.webp) : durée, taille du fichier, arrêt.
    COMPACT_SIZE = (340, 148)

    # Décompte avant le début réel de la capture
    COUNTDOWN_SECONDS = 3

    @staticmethod
    def full_size() -> tuple:
        """Taille de la fenêtre, ajustée à l'écran.

        L'écran cible mesure 1366×768 : une fenêtre de taille fixe y
        dépasserait sous la barre des tâches et couperait les panneaux du
        bas. On prend une marge et on plafonne.
        """
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # SM_CXFULLSCREEN / SM_CYFULLSCREEN : zone utile, barre des
            # tâches exclue
            width = user32.GetSystemMetrics(16)
            height = user32.GetSystemMetrics(17)
            if width > 0 and height > 0:
                return (min(1080, max(880, width - 60)),
                        min(760, max(560, height - 40)))
        except Exception:
            pass
        return (1000, 660)

    def __init__(self, config: Optional[ConfigManager] = None,
                 recorder_factory: Callable[..., RecorderCore] = RecorderCore,
                 encoder_factory: Callable[[], VideoEncoder] = VideoEncoder,
                 hotkey_factory: Callable[..., GlobalHotkey] = GlobalHotkey,
                 analyzer: Optional[SystemAnalyzer] = None):
        self.config = config or ConfigManager()
        self._recorder_factory = recorder_factory
        self._encoder_factory = encoder_factory
        self._hotkey_factory = hotkey_factory
        self.analyzer = analyzer or SystemAnalyzer()

        try:
            self.recommended = self.analyzer.get_recommended_settings()
        except Exception:
            self.recommended = {'resolution': '1280x720', 'fps': 30,
                                'bitrate': '2500k'}

        # Posé par app.py après création. Le préfixe _ est INDISPENSABLE :
        # au chargement de la page, pywebview parcourt récursivement tous
        # les attributs publics du js_api pour les exposer au JS. La
        # fenêtre mène au Form WinForms (window.native), dont les
        # propriétés .NET bouclent à l'infini (Bounds.Empty rend un
        # nouveau Rectangle qui a lui-même .Empty…) : des centaines
        # d'erreurs « maximum recursion depth exceeded » au démarrage.
        # pywebview saute tout attribut commençant par _.
        self._window = None
        self.recorder = None
        self.hotkey = None
        self.state = IDLE

        self._start_time = None
        self._timer_thread = None
        self._emit_lock = threading.Lock()
        self._final_output_path = ""
        self._last_output = ""
        self._compact = False
        self._full_position = None
        self._full_geometry = None

        # Mise à jour automatique. Les deux fonctions sont des attributs
        # pour que les tests les remplacent sans toucher au réseau.
        self._update_info = None
        self._update_installing = False
        self._update_checker = check_for_update
        self._update_downloader = download_setup

        self._purge_temp_files()

    # ------------------------------------------------------------------
    # Envoi d'événements vers la page
    # ------------------------------------------------------------------

    def emit(self, event: str, payload=None):
        """Pousse un événement vers la page.

        Sérialisé : appelé depuis la minuterie, le thread d'encodage et
        celui de post-traitement, qui tournent en même temps.
        """
        if self._window is None:
            return
        with self._emit_lock:
            try:
                data = json.dumps({'event': event, 'payload': payload})
                self._window.evaluate_js(f"window.luminaEvent({data})")
            except Exception as e:
                # La page a pu être fermée entre-temps : ne jamais
                # laisser un échec d'affichage remonter dans un thread de
                # travail, il tuerait l'enregistrement en cours
                print(f"[Lumina] Événement « {event} » non transmis : {e}")

    def _set_state(self, state: str):
        self.state = state
        self.emit('state', state)
        self._apply_window_mode(state)

    def _apply_window_mode(self, state: str):
        """Bascule entre fenêtre pleine et barre compacte.

        Pendant la capture, la fenêtre pleine masquerait l'écran que l'on
        filme ; la réduire complètement priverait l'utilisateur de tout
        retour visuel et du bouton d'arrêt. La barre compacte, posée en
        haut à droite et toujours au-dessus, résout les deux.
        """
        if self._window is None:
            return
        # Le décompte s'affiche déjà dans le widget : basculer dès
        # « pending » évite un saut de fenêtre au moment précis où la
        # capture démarre, qui serait visible dans l'enregistrement.
        compact_states = (PENDING, RECORDING)
        try:
            if state in compact_states and not self._compact:
                # Mémoriser où l'utilisateur avait placé sa fenêtre AVANT
                # de la déplacer : sans cela, on la lui rendait collée au
                # coin où se tenait le widget.
                self._full_position = self._current_position()
                self._full_geometry = self._current_size()
                self._compact = True
                self._window.on_top = True
                # Le widget se passe de bordure : petit, arrondi, déplacé
                # par easy_drag
                self._set_native_frame(False)
                # Visible pour l'utilisateur, absent de la vidéo : sans
                # cela le widget s'incruste en haut à droite de chaque
                # enregistrement
                self._set_capture_affinity(True)
                self._window.resize(*self.COMPACT_SIZE)
                self._window.move(*self._compact_position())
            elif state not in compact_states and self._compact:
                self._compact = False
                self._window.on_top = False
                # Redevenir capturable : l'utilisateur peut vouloir
                # filmer Lumina elle-même avec un autre outil
                self._set_capture_affinity(False)
                # Rendre la bordure : sans elle l'utilisateur ne peut ni
                # déplacer ni redimensionner sa fenêtre
                self._set_native_frame(True)
                self._window.resize(*(self._full_geometry or self.full_size()))
                if self._full_position:
                    self._window.move(*self._full_position)
        except Exception as e:
            # Un échec de redimensionnement ne doit pas interrompre un
            # enregistrement : l'interface est secondaire par rapport à
            # la capture en cours
            print(f"[Lumina] Bascule de fenêtre impossible : {e}")

    # Valeurs de SetWindowDisplayAffinity (winuser.h)
    _WDA_NONE = 0x0
    _WDA_EXCLUDEFROMCAPTURE = 0x11

    def _set_capture_affinity(self, exclude: bool):
        """Rend la fenêtre invisible dans les captures d'écran, pas à
        l'écran.

        SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) : l'utilisateur
        voit le widget sur son moniteur, mais la composition capturée
        par BitBlt/mss se fait sans lui. Mesuré sur machine avant
        d'implémenter : la capture montre le fond derrière la fenêtre,
        pas un rectangle noir. C'est le mécanisme des contrôles de
        Zoom/OBS.

        Échec toléré (Windows antérieur à la 2004, fenêtre de test sans
        handle natif) : le widget reste alors simplement visible dans la
        vidéo, comme avant.
        """
        try:
            import ctypes
            hwnd = int(self._window.native.Handle.ToInt64())
            affinity = (self._WDA_EXCLUDEFROMCAPTURE if exclude
                        else self._WDA_NONE)
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, affinity)
        except Exception:
            pass

    def _set_native_frame(self, visible: bool):
        """Affiche ou masque la bordure native de la fenêtre.

        La fenêtre principale garde sa bordure Windows : elle apporte
        gratuitement le déplacement, le redimensionnement, l'ancrage et
        l'agrandissement au double-clic. Sans elle, il ne reste rien pour
        manipuler la fenêtre — `-webkit-app-region: drag` est une
        propriété Electron, que WebView2 ignore.

        Le widget d'enregistrement, lui, s'en passe : il est petit,
        arrondi, et `easy_drag` suffit à le déplacer.

        Passe par l'objet WinForms interne à pywebview : sans équivalent
        dans l'API publique. Un échec est sans conséquence — on garde la
        bordure telle quelle plutôt que d'interrompre l'enregistrement.
        """
        try:
            import clr  # noqa: F401
            from System.Windows.Forms import FormBorderStyle

            form = self._window.native
            # getattr : « None » est un mot-clé Python, l'attribut ne
            # peut pas être écrit FormBorderStyle.None
            style = (FormBorderStyle.Sizable if visible
                     else getattr(FormBorderStyle, 'None'))
            # L'interface graphique n'appartient pas à ce thread : passer
            # par Invoke, sinon WinForms lève une exception de thread
            if form.InvokeRequired:
                from System import Action
                form.Invoke(Action(lambda: setattr(form, 'FormBorderStyle',
                                                   style)))
            else:
                form.FormBorderStyle = style
            return True
        except Exception as e:
            print(f"[Lumina] Bordure de fenêtre inchangée : {e}")
            return False

    def _current_position(self):
        """Position actuelle de la fenêtre, ou None si illisible.

        L'utilisateur a pu déplacer sa fenêtre : c'est cette position
        qu'il doit retrouver après l'enregistrement, pas celle d'origine.
        """
        try:
            x, y = int(self._window.x), int(self._window.y)
            # Une fenêtre pas encore affichée renvoie parfois 0,0 :
            # inutile de mémoriser une position qui n'a jamais existé
            return (x, y) if (x, y) != (0, 0) else None
        except Exception:
            return None

    def _current_size(self):
        """Taille actuelle de la fenêtre, ou None si illisible.

        L'utilisateur a pu la redimensionner ; on la lui rend telle
        quelle plutôt qu'à la taille calculée au démarrage.
        """
        try:
            width, height = int(self._window.width), int(self._window.height)
            if width < 200 or height < 200:
                return None     # valeur aberrante ou fenêtre non prête
            return (width, height)
        except Exception:
            return None

    def _compact_position(self):
        """Coin haut droit de l'écran, avec une marge."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            screen_w = user32.GetSystemMetrics(0)
            return (screen_w - self.COMPACT_SIZE[0] - 24, 24)
        except Exception:
            return (100, 24)

    # ------------------------------------------------------------------
    # Lecture de l'état initial
    # ------------------------------------------------------------------

    def get_initial_state(self) -> dict:
        """Tout ce dont la page a besoin pour se dessiner."""
        try:
            devices = list_input_devices()
        except Exception:
            devices = []

        options = AIOptions.load(self.config)
        save_dir = self.config.get('output', 'save_directory',
                                   fallback='~/Videos/Lumina')


        return {
            'state': self.state,
            'version': APP_VERSION,
            'profile': getattr(self.analyzer.profile, 'value', 'inconnu'),
            'recommended': self.recommended,
            'resolution': self._resolution(),
            'bitrate': self._bitrate(),
            'fps': self.recommended.get('fps', 30),
            'save_directory': str(Path(save_dir).expanduser()),
            'hotkey': self.config.get('recording', 'hotkey',
                                      fallback=DEFAULT_HOTKEY),
            'hotkey_active': bool(self.hotkey and self.hotkey.is_active),
            'hotkey_error': self.hotkey.error if self.hotkey else "",
            'audio': {
                'mic_enabled': self.config.get_bool('recording',
                                                    'audio_enabled',
                                                    fallback=True),
                'gain': self.config.get_float('recording', 'audio_gain',
                                              fallback=0.5),
                'system_enabled': self.config.get_bool('recording',
                                                       'system_audio',
                                                       fallback=False),
                'system_available': system_audio_is_available(),
                'devices': [{'index': d.index, 'name': d.name,
                             'is_default': d.is_default} for d in devices],
                'selected_device': self.config.get_int(
                    'recording', 'audio_device_index', fallback=-1),
            },
            'smart_focus': {
                'enabled': self.config.get_bool('recording', 'smart_focus',
                                                fallback=False),
                'available': smart_focus_is_available(),
            },
            'ai': {
                'options': options,
                'magic_cut_max': self.config.get('recording',
                                                 'magic_cut_max',
                                                 fallback='3 s'),
                'delete_original': self.config.get_bool('recording',
                                                        'delete_original',
                                                        fallback=False),
                # Ce qui est réellement installé : la page grise les
                # cases correspondantes plutôt que de faire croire à une
                # fonctionnalité active
                'available': {
                    'subtitles': whisper_is_available(),
                    'privacy_blur': ocr_is_available(),
                    # Ces deux-là ont besoin d'un fournisseur IA ET des
                    # sous-titres, dont ils lisent le .srt
                    'summary': bool(build_engine_from_config(self.config))
                                and whisper_is_available(),
                    'subtitle_fix': bool(build_engine_from_config(self.config))
                                     and whisper_is_available(),
                },
                'provider': self.config.get('ai', 'provider',
                                            fallback=DEFAULT_PROVIDER),
            },
        }

    # ------------------------------------------------------------------
    # Réglages
    # ------------------------------------------------------------------

    # (clé envoyée par la page) -> (section .ini, clé .ini)
    SIMPLE_KEYS = {
        'resolution': ('recording', 'default_resolution'),
        'bitrate': ('recording', 'default_bitrate'),
        'mic_enabled': ('recording', 'audio_enabled'),
        'gain': ('recording', 'audio_gain'),
        'system_audio': ('recording', 'system_audio'),
        'smart_focus': ('recording', 'smart_focus'),
        'magic_cut_max': ('recording', 'magic_cut_max'),
        'delete_original': ('recording', 'delete_original'),
        'audio_device_index': ('recording', 'audio_device_index'),
        'save_directory': ('output', 'save_directory'),
    }

    def set_option(self, key: str, value) -> dict:
        """Modifie un réglage et le persiste immédiatement."""
        try:
            if key in self.SIMPLE_KEYS:
                section, ini_key = self.SIMPLE_KEYS[key]
                self.config.set(section, ini_key, value)
                return {'ok': True}

            if key in AIOptions.KEYS:
                options = AIOptions.load(self.config)
                options[key] = bool(value)
                AIOptions.save(self.config, options)
                return {'ok': True}

            return {'ok': False, 'error': f"Réglage inconnu : {key}"}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # Fournisseurs IA
    # ------------------------------------------------------------------

    def get_ai_config(self) -> dict:
        """État des fournisseurs IA, pour le panneau de configuration.

        Ne renvoie JAMAIS de clé en clair : `providers_status` les masque.
        Une clé exposée à la page serait lisible par tout script qui s'y
        exécute.
        """
        provider = self.config.get('ai', 'provider', fallback=DEFAULT_PROVIDER)
        model = self.config.get('ai', 'model', fallback='')
        engine = build_engine_from_config(self.config)

        return {
            'provider': provider,
            'model': model,
            'providers': providers_status(),
            # « Configuré » ne veut pas dire « joignable » : Ollama peut
            # être choisi sans être lancé. On teste réellement.
            'ready': bool(engine and self._engine_reachable(engine)),
            'sends_offsite': sends_data_offsite(provider),
            'local_models': self._local_models(),
        }

    @staticmethod
    def _engine_reachable(engine) -> bool:
        """Le fournisseur répond-il vraiment ?

        Pour Ollama, is_available() interroge le service local ; pour les
        API distantes, il vérifie seulement la présence d'une clé — on ne
        consomme pas de crédit juste pour afficher un état.
        """
        try:
            return bool(engine.is_available())
        except Exception:
            return False

    def _local_models(self) -> list:
        """Modèles installés dans Ollama, s'il tourne."""
        try:
            engine = build_engine('ollama')
            return engine.list_local_models() if engine else []
        except Exception:
            return []

    def set_ai_provider(self, provider: str, model: str = '') -> dict:
        """Choisit le fournisseur et le modèle. La clé n'est pas ici."""
        if provider not in PROVIDERS:
            return {'ok': False, 'error': f"Fournisseur inconnu : {provider}"}
        try:
            chosen = model or PROVIDERS[provider]['default_model']
            # Le modèle par défaut d'Ollama n'est pas forcément installé.
            # Proposer un modèle absent donnerait un 404 au premier usage,
            # après l'enregistrement : autant prendre ce qui est là.
            if provider == 'ollama' and not model:
                installed = self._local_models()
                if installed and chosen not in installed:
                    chosen = installed[0]

            self.config.set('ai', 'provider', provider)
            self.config.set('ai', 'model', chosen)
            return {'ok': True, 'config': self.get_ai_config()}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def set_ai_key(self, provider: str, api_key: str) -> dict:
        """Enregistre une clé API dans le coffre Windows.

        La clé traverse le pont depuis la page, mais n'y retourne jamais :
        la réponse ne contient que l'état, avec une version masquée.
        """
        if provider not in PROVIDERS:
            return {'ok': False, 'error': f"Fournisseur inconnu : {provider}"}
        if not set_api_key(provider, api_key or ''):
            return {'ok': False,
                    'error': "Coffre Windows indisponible : la clé n'a pas "
                             "été enregistrée"}
        return {'ok': True, 'config': self.get_ai_config()}

    def test_ai_provider(self) -> dict:
        """Interroge réellement le fournisseur configuré.

        Une clé enregistrée peut être invalide, et Ollama peut être
        choisi sans tourner : seul un appel réel le dit.
        """
        engine = build_engine_from_config(self.config)
        if engine is None:
            return {'ok': False,
                    'error': "Aucun fournisseur configuré (clé manquante ?)"}
        try:
            answer = engine.generate_text(
                "Réponds uniquement par le mot OK.",
                "Tu réponds en un seul mot.")
            if not answer or not answer.strip():
                return {'ok': False,
                        'error': "Le fournisseur n'a renvoyé aucune réponse"}
            return {'ok': True, 'answer': answer.strip()[:60]}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def choose_folder(self) -> dict:
        """Ouvre le sélecteur de dossier natif."""
        if self._window is None:
            return {'ok': False, 'error': "Fenêtre indisponible"}
        try:
            import webview
            result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
            if result:
                folder = result[0] if isinstance(result, (list, tuple)) else result
                self.config.set('output', 'save_directory', folder)
                return {'ok': True, 'path': folder}
            return {'ok': False, 'cancelled': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def open_output_folder(self) -> dict:
        """Ouvre l'explorateur sur le dernier fichier produit."""
        target = self._last_output or self.config.get(
            'output', 'save_directory', fallback='')
        target = str(Path(target).expanduser())
        try:
            if os.path.isfile(target):
                subprocess.Popen(['explorer', '/select,', target])
            elif os.path.isdir(target):
                os.startfile(target)
            else:
                return {'ok': False, 'error': "Dossier introuvable"}
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # Enregistrement
    # ------------------------------------------------------------------

    def toggle_recording(self) -> dict:
        """Bascule démarrage/arrêt — c'est ce qu'appelle le raccourci."""
        if self.state == RECORDING:
            return self.stop_recording()
        if self.state == IDLE:
            return self.start_recording()
        # pending ou processing : ne rien faire, comme le garde _busy de
        # l'interface tkinter
        return {'ok': False, 'busy': True}

    def start_recording(self) -> dict:
        if self.state != IDLE:
            return {'ok': False, 'error': "Enregistrement déjà en cours"}

        try:
            # FFmpeg doit être présent AVANT de capturer quoi que ce soit :
            # sinon on enregistre pour rien et l'échec n'apparaît qu'à la fin
            self._encoder_factory()
        except FileNotFoundError as e:
            return {'ok': False, 'error': str(e)}

        try:
            save_dir = Path(self.config.get('output', 'save_directory',
                                            fallback='~/Videos/Lumina')
                            ).expanduser()
            save_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._final_output_path = str(save_dir / f"Lumina_{timestamp}.mp4")

            options = AIOptions.load(self.config)
            self.recorder = self._recorder_factory(
                resolution=self._resolution(),
                fps=self.recommended.get('fps', 30),
                audio_enabled=self.config.get_bool('recording',
                                                   'audio_enabled',
                                                   fallback=True),
                audio_gain=self.config.get_float('recording', 'audio_gain',
                                                 fallback=0.5),
                audio_device_index=self._selected_device_index(),
                filters=AIOptions.build_filters(
                    options, plugins_actifs=self._plugins_actifs()),
                on_filter_disabled=lambda n: self.emit(
                    'notice', f"Filtre « {n} » désactivé (trop lent)"),
                on_capture_error=lambda m: self.emit('error', m),
                on_audio_error=lambda m: self.emit('notice', m),
                system_audio_enabled=self.config.get_bool('recording',
                                                          'system_audio',
                                                          fallback=False),
                smart_focus_enabled=self.config.get_bool('recording',
                                                         'smart_focus',
                                                         fallback=False),
                on_smart_focus=lambda m: self.emit('notice', m),
            )
        except Exception as e:
            return {'ok': False, 'error': f"Préparation impossible : {e}"}

        # Décompte avant capture : l'utilisateur voit 3, 2, 1 et sait
        # exactement quand l'enregistrement commence. Il sert aussi au
        # Smart Focus, qui a besoin de ce délai pour que l'utilisateur
        # clique sur sa fenêtre cible — sinon Lumina se filmerait
        # elle-même, étant au premier plan au moment du clic. Un seul
        # délai pour les deux besoins plutôt que deux qui s'additionnent.
        self._set_state(PENDING)
        threading.Thread(target=self._countdown, daemon=True).start()
        return {'ok': True, 'pending': True,
                'countdown': self.COUNTDOWN_SECONDS}

    def _countdown(self):
        """Égrène le décompte puis démarre réellement la capture."""
        for remaining in range(self.COUNTDOWN_SECONDS, 0, -1):
            if self.state != PENDING:
                return          # annulé entre-temps
            self.emit('countdown', remaining)
            time.sleep(1.0)

        if self.state != PENDING:
            return
        # 0 affiché brièvement : sans cela le dernier chiffre saute
        self.emit('countdown', 0)

        result = self._launch()
        if not result.get('ok'):
            self.emit('error', result.get('error', "Échec du démarrage"))

    def _launch(self) -> dict:
        try:
            if not self.recorder.start_recording(self._final_output_path):
                self._set_state(IDLE)
                return {'ok': False, 'error': "Le moteur a refusé de démarrer"}
        except Exception as e:
            self._set_state(IDLE)
            return {'ok': False, 'error': str(e)}

        self._start_time = time.time()
        self._set_state(RECORDING)
        self._start_timer()
        return {'ok': True}

    def _recorded_bytes(self, seconds: float = None) -> int:
        """Taille estimée du fichier FINAL, pas du fichier brut.

        Le brut est un AVI quasi non compressé qui gonfle de plusieurs
        Mo par seconde avant d'être jeté après encodage : l'afficher
        faisait croire à l'utilisateur qu'une capture d'une seconde
        pesait déjà 7 ou 20 Mo. Ce qu'il obtiendra réellement est le
        MP4, dont la taille découle du débit d'encodage — c'est donc
        elle qu'on estime : (débit vidéo + débit audio) × durée.
        """
        if seconds is None:
            seconds = max(0.0, time.time() - (self._start_time or time.time()))
        video_kbps = self._bitrate_kbps()
        # 192k : le débit AAC de l'encodeur (voir encoder.py). Compté
        # seulement si une piste audio existera dans le fichier final.
        audio_kbps = 192 if (
            self.config.get_bool('recording', 'audio_enabled', fallback=True)
            or self.config.get_bool('recording', 'system_audio',
                                    fallback=False)) else 0
        return int(seconds * (video_kbps + audio_kbps) * 1000 / 8)

    def _bitrate_kbps(self) -> float:
        """Débit vidéo configuré, en kbit/s. « 2500k » -> 2500."""
        raw = str(self._bitrate()).strip().lower()
        try:
            if raw.endswith('m'):
                return float(raw[:-1]) * 1000
            if raw.endswith('k'):
                return float(raw[:-1])
            return float(raw)
        except ValueError:
            return 2500.0

    def _start_timer(self):
        def run():
            while self.state == RECORDING:
                seconds = int(time.time() - self._start_time)
                self.emit('tick', {
                    'seconds': seconds,
                    'bytes': self._recorded_bytes(seconds),
                })
                time.sleep(1.0)
        self._timer_thread = threading.Thread(target=run, daemon=True)
        self._timer_thread.start()

    def stop_recording(self) -> dict:
        if self.state not in (RECORDING, PENDING):
            return {'ok': False, 'error': "Aucun enregistrement en cours"}

        if self.state == PENDING:
            # Annulation pendant le délai du Smart Focus : rien n'a encore
            # été capturé
            self._set_state(IDLE)
            return {'ok': True, 'cancelled': True}

        self._set_state(PROCESSING)
        # Encodage et post-traitement dans un thread : bloquer ici gèlerait
        # la fenêtre pendant toute la durée du traitement
        threading.Thread(target=self._finish, daemon=True).start()
        return {'ok': True}

    def _finish(self):
        """Arrêt, encodage, post-traitement. Tourne hors du fil PyWebView."""
        import shutil
        preserved_audio = None
        try:
            self.emit('progress', {'step': "Arrêt de la capture",
                                   'value': 0.05})
            result = self.recorder.stop_recording()
            if not result:
                self.emit('error', "Aucune image capturée")
                self._set_state(IDLE)
                return

            raw_video, raw_audio = result
            options = AIOptions.load(self.config)

            # Le WAV sert encore aux sous-titres et à Magic Cut, mais
            # l'encodeur supprime les temporaires après fusion
            needs_audio = options.get('subtitles') or options.get('magic_cut')
            if needs_audio and raw_audio and os.path.exists(raw_audio):
                preserved_audio = raw_audio + ".keep.wav"
                shutil.copyfile(raw_audio, preserved_audio)

            self.emit('progress', {'step': "Encodage", 'value': 0.2})
            encoder = self._encoder_factory()
            success = encoder.encode(
                video_path=raw_video,
                audio_path=raw_audio,
                output_path=self._final_output_path,
                resolution=self._resolution(),
                fps=int(round(getattr(self.recorder, 'actual_fps',
                                      self.recommended.get('fps', 30)))),
                bitrate=self._bitrate(),
                audio_gain=1.0,   # le gain est déjà appliqué à la capture
                system_audio_path=getattr(self.recorder, 'system_audio_path',
                                          '') or None,
            )

            if not success:
                self.emit('error', "L'encodage a échoué")
                self._set_state(IDLE)
                return

            self._last_output = self._final_output_path
            processors = AIOptions.build_postprocessors(
                options,
                self.config.get('recording', 'magic_cut_max', fallback='3 s'),
                self.config.get_bool('recording', 'delete_original',
                                     fallback=False),
                # None si aucun fournisseur n'est configuré : les
                # traitements qui en dépendent sont alors absents de la
                # chaîne plutôt qu'ajoutés pour échouer
                ai_engine=build_engine_from_config(self.config))

            results = []
            if processors:
                results = run_postprocessors(
                    processors, self._final_output_path, preserved_audio,
                    lambda p: self.emit('progress',
                                        {'step': "Traitement IA",
                                         'value': 0.3 + 0.7 * p}),
                    step_cb=lambda n: self.emit('progress',
                                                {'step': n, 'value': None}))

            self.emit('done', {
                'path': self._final_output_path,
                'exists': os.path.exists(self._final_output_path),
                'results': [{'name': r.name, 'success': r.success,
                             'output': r.output_path, 'error': r.error}
                            for r in results],
            })
        except Exception as e:
            self.emit('error', f"Traitement interrompu : {e}")
        finally:
            # Le .keep.wav pèse plusieurs centaines de Mo par heure : il
            # ne doit pas survivre à un échec
            if preserved_audio and os.path.exists(preserved_audio):
                try:
                    os.remove(preserved_audio)
                except OSError:
                    pass
            self._set_state(IDLE)

    # ------------------------------------------------------------------
    # Raccourci global
    # ------------------------------------------------------------------

    def setup_hotkey(self) -> bool:
        """Enregistre le raccourci global. Un échec n'est pas bloquant."""
        label = self.config.get('recording', 'hotkey', fallback=DEFAULT_HOTKEY)
        self.hotkey = self._hotkey_factory(
            label, on_pressed=self._on_hotkey_pressed)
        return self.hotkey.start()

    def _on_hotkey_pressed(self):
        """Appelé depuis le thread du raccourci, jamais depuis la page."""
        try:
            self.toggle_recording()
        except Exception as e:
            print(f"[Lumina] Raccourci : {e}")

    # ------------------------------------------------------------------
    # Plugins
    # ------------------------------------------------------------------

    def get_plugins(self) -> dict:
        """Liste les plugins installés, avec leur état d'activation.

        Aucun code de plugin n'est exécuté ici : les métadonnées sont
        lues par analyse syntaxique du fichier.
        """
        actifs = self._plugins_actifs()
        try:
            trouves = lister_plugins()
        except Exception as e:
            # L'interface doit s'ouvrir même si le dossier pose problème
            return {'ok': False, 'error': str(e), 'plugins': []}

        return {
            'ok': True,
            'dossier': str(plugins_dir()),
            'plugins': [{
                'identifiant': p.identifiant,
                'nom': p.nom,
                'description': p.description,
                'auteur': p.auteur,
                'version': p.version,
                'erreur': p.erreur,
                # Un plugin refusé n'est jamais annoncé actif, même si
                # la configuration le liste : il ne sera pas chargé
                'actif': p.identifiant in actifs and p.utilisable,
            } for p in trouves],
        }

    def _plugins_actifs(self) -> list:
        """Identifiants des plugins activés, lus dans la configuration."""
        brut = self.config.get('plugins', 'actifs', fallback='') or ''
        return [x.strip() for x in str(brut).split(',') if x.strip()]

    def set_plugin_actif(self, identifiant: str, actif: bool) -> dict:
        """Active ou désactive un plugin.

        Prend effet au prochain enregistrement : changer la chaîne de
        filtres pendant une capture en cours la ferait vaciller.
        """
        actifs = self._plugins_actifs()
        if actif and identifiant not in actifs:
            actifs.append(identifiant)
        elif not actif and identifiant in actifs:
            actifs.remove(identifiant)

        self.config.set('plugins', 'actifs', ','.join(actifs))
        try:
            self.config.save()
        except Exception:
            # FakeConfig des tests n'a pas de save() ; en production un
            # échec d'écriture ne doit pas casser l'interface
            pass
        return {'ok': True}

    def open_plugins_folder(self) -> dict:
        """Ouvre le dossier des plugins dans l'explorateur."""
        dossier = plugins_dir()
        try:
            dossier.mkdir(parents=True, exist_ok=True)
            os.startfile(str(dossier))
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    # ------------------------------------------------------------------
    # Mise à jour automatique
    # ------------------------------------------------------------------

    def start_update_watch(self):
        """Vérifie en arrière-plan si une release plus récente existe.

        Lancée une fois la fenêtre prête. Silencieuse par nature : hors
        ligne ou sans release publiée, il ne se passe rien du tout. Se
        désactive avec [updates] check_on_start = false dans la config.
        """
        if not self.config.get_bool('updates', 'check_on_start',
                                    fallback=True):
            return

        def run():
            # La page d'abord, la mise à jour ensuite : rien ne doit
            # ralentir l'affichage initial
            time.sleep(3.0)
            info = self._update_checker(APP_VERSION)
            if info is not None:
                self._update_info = info
                self.emit('update_available', {
                    'version': info.version,
                    'notes': info.notes,
                    'size': info.size,
                })

        threading.Thread(target=run, daemon=True).start()

    def check_updates_now(self) -> dict:
        """Vérification à la demande (bouton de l'interface)."""
        try:
            info = self._update_checker(APP_VERSION)
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        if info is None:
            return {'ok': True, 'available': False, 'version': APP_VERSION}
        self._update_info = info
        return {'ok': True, 'available': True, 'version': info.version,
                'notes': info.notes, 'size': info.size}

    def install_update(self) -> dict:
        """Télécharge le setup puis le lance ; l'application se ferme.

        Le setup NSIS fait le reste : fermeture de l'application,
        désinstallation silencieuse de l'ancienne version, installation
        de la nouvelle, réglages et clés API conservés.
        """
        if self.state != IDLE:
            return {'ok': False,
                    'error': "Terminez l'enregistrement avant de mettre à jour"}
        if self._update_info is None:
            return {'ok': False, 'error': "Aucune mise à jour disponible"}
        if self._update_installing:
            return {'ok': False, 'error': "Téléchargement déjà en cours"}
        self._update_installing = True

        def run():
            try:
                dest = os.path.join(str(get_temp_dir()), 'updates')
                path = self._update_downloader(
                    self._update_info, dest,
                    progress_cb=lambda p: self.emit('update_progress', p))
                self.emit('update_launching', None)
                os.startfile(path)
                # Laisser l'événement atteindre la page avant de fermer
                time.sleep(1.5)
                self.shutdown()
                if self._window is not None:
                    self._window.destroy()
            except Exception as e:
                self._update_installing = False
                self.emit('update_error',
                          f"Mise à jour impossible : {e}")

        threading.Thread(target=run, daemon=True).start()
        return {'ok': True}

    # ------------------------------------------------------------------
    # Divers
    # ------------------------------------------------------------------

    def minimize(self) -> dict:
        """Réduit la fenêtre (bouton de la barre de titre)."""
        try:
            self._window.minimize()
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def close(self) -> dict:
        """Ferme l'application (bouton de la barre de titre)."""
        try:
            self.shutdown()
            self._window.destroy()
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def _resolution(self) -> str:
        """Résolution effective : le .ini peut contenir « auto »."""
        value = self.config.get('recording', 'default_resolution',
                                fallback='auto')
        if not value or value == 'auto':
            return self.recommended.get('resolution', '1280x720')
        return value

    def _bitrate(self) -> str:
        """Débit effectif : le .ini peut contenir « auto »."""
        value = self.config.get('recording', 'default_bitrate',
                                fallback='auto')
        if not value or value == 'auto':
            return self.recommended.get('bitrate', '2500k')
        return value

    def _selected_device_index(self) -> Optional[int]:
        index = self.config.get_int('recording', 'audio_device_index',
                                    fallback=-1)
        return None if index < 0 else index

    def _purge_temp_files(self):
        """Supprime les .keep.wav orphelins d'une session interrompue."""
        try:
            for f in get_temp_dir().glob("*.keep.wav"):
                try:
                    f.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    def shutdown(self):
        """Fermeture propre : raccourci libéré, capture arrêtée.

        Sans cela, Windows garderait le raccourci jusqu'à la fin de la
        session et le thread de capture survivrait à la fenêtre, laissant
        un .avi jamais finalisé.
        """
        if self.hotkey is not None:
            self.hotkey.stop()
        if self.recorder is not None and self.recorder.is_recording:
            try:
                self.recorder.stop_recording()
            except Exception as e:
                print(f"[Lumina] Arrêt à la fermeture : {e}")
