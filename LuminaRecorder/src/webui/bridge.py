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
from services.ocr_service import ocr_is_available
from utils.config_manager import ConfigManager


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

        self.window = None          # posé par app.py après création
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

        self._purge_temp_files()

    # ------------------------------------------------------------------
    # Envoi d'événements vers la page
    # ------------------------------------------------------------------

    def emit(self, event: str, payload=None):
        """Pousse un événement vers la page.

        Sérialisé : appelé depuis la minuterie, le thread d'encodage et
        celui de post-traitement, qui tournent en même temps.
        """
        if self.window is None:
            return
        with self._emit_lock:
            try:
                data = json.dumps({'event': event, 'payload': payload})
                self.window.evaluate_js(f"window.luminaEvent({data})")
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
        if self.window is None:
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
                self.window.on_top = True
                # Le widget se passe de bordure : petit, arrondi, déplacé
                # par easy_drag
                self._set_native_frame(False)
                self.window.resize(*self.COMPACT_SIZE)
                self.window.move(*self._compact_position())
            elif state not in compact_states and self._compact:
                self._compact = False
                self.window.on_top = False
                # Rendre la bordure : sans elle l'utilisateur ne peut ni
                # déplacer ni redimensionner sa fenêtre
                self._set_native_frame(True)
                self.window.resize(*(self._full_geometry or self.full_size()))
                if self._full_position:
                    self.window.move(*self._full_position)
        except Exception as e:
            # Un échec de redimensionnement ne doit pas interrompre un
            # enregistrement : l'interface est secondaire par rapport à
            # la capture en cours
            print(f"[Lumina] Bascule de fenêtre impossible : {e}")

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

            form = self.window.native
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
            x, y = int(self.window.x), int(self.window.y)
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
            width, height = int(self.window.width), int(self.window.height)
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
                },
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

    def choose_folder(self) -> dict:
        """Ouvre le sélecteur de dossier natif."""
        if self.window is None:
            return {'ok': False, 'error': "Fenêtre indisponible"}
        try:
            import webview
            result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
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
                filters=AIOptions.build_filters(options),
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

    def _recorded_bytes(self) -> int:
        """Taille du fichier brut en cours d'écriture.

        Le widget l'affiche pour que l'utilisateur voie la capture
        progresser réellement, et repère un enregistrement qui grossit
        trop vite avant de remplir son disque.
        """
        path = getattr(self.recorder, '_raw_video_path', '') or ''
        try:
            return os.path.getsize(path) if path else 0
        except OSError:
            # Le fichier n'existe pas encore à la première seconde
            return 0

    def _start_timer(self):
        def run():
            while self.state == RECORDING:
                self.emit('tick', {
                    'seconds': int(time.time() - self._start_time),
                    'bytes': self._recorded_bytes(),
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
                                     fallback=False))

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
    # Divers
    # ------------------------------------------------------------------

    def minimize(self) -> dict:
        """Réduit la fenêtre (bouton de la barre de titre)."""
        try:
            self.window.minimize()
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def close(self) -> dict:
        """Ferme l'application (bouton de la barre de titre)."""
        try:
            self.shutdown()
            self.window.destroy()
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
