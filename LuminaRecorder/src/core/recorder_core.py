"""
Lumina Recorder - Core Recording Engine
Gère la capture d'écran et audio avec optimisation selon le profil système.
"""

import re
import time
import threading
import mss
import mss.tools
import numpy as np
import cv2
import pyaudio
import wave
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple, Dict, List, Callable
from pathlib import Path

from filters.base import FilterChain, FrameFilter
from core.system_audio import SystemAudioCapture, system_audio_is_available
from core.focus_tracker import FocusTracker, smart_focus_is_available


@dataclass
class AudioDevice:
    """Périphérique d'entrée audio proposé à l'utilisateur"""
    index: int
    name: str
    max_channels: int
    is_default: bool


def get_temp_dir() -> Path:
    """Dossier des fichiers bruts d'enregistrement.

    Ancré sur les données applicatives de l'utilisateur plutôt que sur
    os.getcwd() : lancée depuis un raccourci ou empaquetée avec
    PyInstaller, l'application écrirait sinon dans un dossier arbitraire,
    potentiellement non inscriptible (Program Files).
    """
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return Path(base) / 'LuminaRecorder' / 'temp'
    return Path.home() / '.cache' / 'lumina_recorder'


def _decode_device_name(raw: str) -> str:
    """Répare les noms PyAudio mal décodés sous Windows.

    PortAudio renvoie de l'UTF-8 interprété en latin-1 ("RÃ©seau" au lieu
    de "Réseau"). Le re-encodage restaure les accents ; si la chaîne n'est
    pas concernée, elle est renvoyée telle quelle.
    """
    try:
        return raw.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def clean_device_name(raw: str) -> str:
    """Rend lisible un nom de périphérique Windows.

    Windows expose des noms bruts issus des pilotes, du genre
    « Input (@System32\\drivers\\bthhfenum.sys,#4;%1 Hands-Free HF
    Audio%0 ;(iPhone)) ». Le seul fragment utile pour l'utilisateur est
    le nom de l'appareil, entre les dernières parenthèses.
    """
    name = _decode_device_name(str(raw).strip())

    # Chemin de pilote : ne garder que l'appareil nommé en fin de chaîne
    if '@System32' in name or '.sys,' in name:
        appareil = re.findall(r'\(([^()]+)\)\s*\)?\s*$', name)
        if appareil:
            return appareil[0].strip()
        # Repli : le texte avant la parenthèse ouvrante
        return name.split('(')[0].strip() or name

    # Suffixe technique du pilote entre parenthèses : « Réseau de
    # microphones (Realtek HD Audio Mic Array input) » et « Réseau de
    # microphones (Realtek Audio) » désignent le MÊME micro, exposé par
    # deux API hôtes. Retirer le suffixe les rend identiques, donc
    # dédoublonnables — c'est ce qui produisait trois entrées visuellement
    # indiscernables dans la liste.
    sans_suffixe = re.sub(r'\s*\((?:[^()]*\b(?:Realtek|Audio|input|Input|'
                          r'HD|USB|WASAPI|MME|DirectSound)\b[^()]*)\)\s*$',
                          '', name).strip()
    if sans_suffixe:
        name = sans_suffixe

    # Parenthèses vides laissées par le nettoyage : « Ligne () »
    name = re.sub(r'\s*\(\s*\)\s*$', '', name).strip()

    # Parenthèse ouverte jamais refermée : l'API MME de Windows tronque
    # les noms à 31 caractères, ce qui produit « Réseau de microphones
    # (Realtek ». Couper au niveau de la parenthèse rend le nom propre
    # ET identique à sa version non tronquée, donc dédoublonnable.
    if name.count('(') > name.count(')'):
        name = name[:name.rindex('(')].strip()

    return name


def list_input_devices() -> List[AudioDevice]:
    """Liste les micros disponibles, sans doublons ni noms illisibles.

    PortAudio expose la MÊME carte via plusieurs API hôtes (MME,
    WASAPI, DirectSound) : la liste brute contenait jusqu'à trois
    entrées strictement identiques, impossibles à distinguer pour
    l'utilisateur. On ne garde qu'une entrée par nom, en privilégiant
    le périphérique par défaut du système.

    Retourne une liste vide si le sous-système audio est indisponible :
    l'absence de micro ne doit jamais empêcher l'application de démarrer.
    """
    devices: List[AudioDevice] = []
    p = None
    try:
        p = pyaudio.PyAudio()
        try:
            default_index = p.get_default_input_device_info()['index']
        except Exception:
            default_index = None

        vus = {}          # nom nettoyé -> position dans `devices`
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info.get('maxInputChannels', 0) <= 0:
                continue

            nom = clean_device_name(info.get('name', f'Périphérique {i}'))
            if not nom:
                continue
            est_defaut = (i == default_index)

            if nom in vus:
                # Doublon : ne le remplacer que si celui-ci est le
                # périphérique par défaut du système, plus fiable
                if est_defaut:
                    devices[vus[nom]] = AudioDevice(
                        index=i, name=nom,
                        max_channels=int(info['maxInputChannels']),
                        is_default=True)
                continue

            vus[nom] = len(devices)
            devices.append(AudioDevice(
                index=i,
                name=nom,
                max_channels=int(info['maxInputChannels']),
                is_default=est_defaut,
            ))
    except Exception as e:
        print(f"[Lumina] Impossible de lister les micros: {e}")
    finally:
        if p is not None:
            try:
                p.terminate()
            except Exception:
                pass

    return devices


class RecorderCore:
    """
    Moteur principal d'enregistrement de Lumina.
    Capture vidéo (écran) et audio (micro/système) de manière synchronisée.
    """
    
    def __init__(self, resolution: str = "1920x1080", fps: int = 30,
                 audio_enabled: bool = True, audio_gain: float = 0.5,
                 filters: Optional[List[FrameFilter]] = None,
                 on_filter_disabled: Optional[Callable[[str], None]] = None,
                 on_capture_error: Optional[Callable[[str], None]] = None,
                 audio_device_index: Optional[int] = None,
                 on_audio_error: Optional[Callable[[str], None]] = None,
                 system_audio_enabled: bool = False,
                 smart_focus_enabled: bool = False,
                 on_smart_focus: Optional[Callable[[str], None]] = None):
        self.resolution = resolution
        self.fps = fps
        self.audio_enabled = audio_enabled
        self.audio_gain = audio_gain
        # None = micro par défaut du système
        self.audio_device_index = audio_device_index
        self.on_audio_error = on_audio_error
        self.system_audio_enabled = system_audio_enabled
        self._system_capture = None
        self.system_audio_path = ""
        # FPS réellement atteint, mesuré à l'arrêt (voir stop_recording)
        self.actual_fps = float(fps)
        self._t0 = None

        self.filter_chain = FilterChain(
            filters or [],
            frame_budget=1.0 / fps,
            on_disable=on_filter_disabled
        )
        self.on_capture_error = on_capture_error

        self.is_recording = False
        self.recording_thread = None
        self.audio_thread = None
        # Signalé au 1er chunk audio : synchronise le départ des 2 pistes
        self._audio_ready = threading.Event()

        self.audio_frames = []
        # Flux brut MJPEG, ouvert à la 1re frame (voir _write_frame)
        self._raw_file = None
        self._raw_origin = None        # seconde zéro des créneaux
        self._last_jpg = None          # dernière image encodée
        self._packets_written = 0      # créneaux écrits à cadence nominale
        self._frame_size = None        # (w, h) figé à l'ouverture du writer
        self._size_mismatch_logged = False
        self._raw_video_path = ""
        self._frame_count = 0
        self._temp_dir = str(get_temp_dir())

        self.start_time = None
        self.output_path = None

        # Configuration MSS pour la capture d'écran
        self.sct = mss.mss()
        self.monitor = self._get_monitor_from_resolution(resolution)

        # Smart Focus : suit la fenêtre active au lieu de l'écran entier.
        # Le verrouillage a lieu au démarrage (voir start_recording), pas
        # ici : la fenêtre au premier plan à la construction est celle de
        # Lumina, pas celle que l'utilisateur veut filmer.
        self.smart_focus_enabled = smart_focus_enabled
        self.on_smart_focus = on_smart_focus
        self._focus_tracker = None

        # Configuration Audio
        self.audio_format = pyaudio.paInt16
        self.channels = 2
        self.sample_rate = 44100
        self.chunk_size = 1024
        
    def _get_monitor_from_resolution(self, resolution: str) -> dict:
        """Sélectionne le moniteur ou la zone basée sur la résolution"""
        try:
            width, height = map(int, resolution.split('x'))
            # Prend le premier moniteur par défaut, on pourrait étendre pour multi-écrans
            monitors = self.sct.monitors
            if len(monitors) > 1:
                # Utilise le moniteur principal (index 1)
                return monitors[1]
            return monitors[0]
        except Exception:
            return self.sct.monitors[0]
    
    def start_recording(self, output_path: str) -> bool:
        """Démarre l'enregistrement"""
        if self.is_recording:
            print("[Lumina] Enregistrement déjà en cours.")
            return False

        self.output_path = output_path
        self.is_recording = True
        # Origine provisoire : recalée plus bas, une fois le micro prêt,
        # pour que le son système et la vidéo partagent bien la même
        # seconde zéro
        self._t0 = time.time()
        self.audio_frames = []
        self._raw_file = None
        self._raw_origin = None
        self._last_jpg = None
        self._packets_written = 0
        self._frame_size = None
        self._size_mismatch_logged = False
        self._raw_video_path = ""
        self._frame_count = 0
        self.start_time = datetime.now()

        print(f"[Lumina] Démarrage de l'enregistrement : "
              f"{self.resolution} @ {self.fps} FPS")

        # Smart Focus : verrouiller la fenêtre AVANT la première frame,
        # sinon la première image serait plein écran et fixerait la
        # résolution du fichier
        self._lock_smart_focus()

        # L'audio démarre en premier : l'ouverture de PortAudio prend
        # ~1 s, pendant laquelle la vidéo tournerait sans son. On attend
        # le premier chunk pour que les deux pistes commencent ensemble,
        # sinon -shortest tronque la vidéo de cette seconde.
        if self.audio_enabled:
            # Nouvel Event plutôt que .clear() : si le thread audio du run
            # précédent est encore vivant (join(timeout=2.0) sans vérifier
            # son retour), son `finally: self._audio_ready.set()` tardif
            # ne doit pas débloquer la vidéo de CE run. Il gardera une
            # référence à l'ancien Event, inoffensive.
            self._audio_ready = threading.Event()
            self.audio_thread = threading.Thread(target=self._capture_audio)
            self.audio_thread.daemon = True
            self.audio_thread.start()
            if not self._audio_ready.wait(timeout=5.0):
                print("[Lumina] Audio lent à démarrer, capture vidéo lancée")

        # L'attente du micro ci-dessus a consommé du temps réel (~1 s le
        # temps que PortAudio ouvre son flux). L'origine commune doit
        # donc être RECALÉE ici, juste avant que le son système et la
        # vidéo ne démarrent ensemble.
        #
        # Mesuré : sans ce recalage, le son système était daté depuis
        # l'appel à start_recording, soit 1,1 s avant la première image.
        # get_audio_bytes réinsérait fidèlement ce silence en tête, et
        # tout le son système se retrouvait en avance d'une seconde sur
        # l'image — flagrant sur une vidéo dont on entend la bande-son
        # avant de la voir.
        self._t0 = time.time()

        # Son système (loopback) : indépendant du micro, les deux peuvent
        # tourner ensemble et seront mixés par FFmpeg
        if self.system_audio_enabled:
            self._system_capture = SystemAudioCapture(gain=self.audio_gain)
            if not self._system_capture.start(reference_time=self._t0):
                self._system_capture = None
                msg = ("Son système indisponible "
                       "(installez PyAudioWPatch)")
                print(f"[Lumina] {msg}")
                if self.on_audio_error:
                    self.on_audio_error(msg)

        self.recording_thread = threading.Thread(target=self._capture_screen)
        self.recording_thread.daemon = True
        self.recording_thread.start()

        return True

    def stop_recording(self) -> Optional[Tuple[str, str]]:
        """Arrête l'enregistrement, retourne (chemin vidéo brute, chemin audio)."""
        if not self.is_recording:
            return None

        self.is_recording = False

        if self.recording_thread:
            self.recording_thread.join(timeout=2.0)
        if self.audio_thread:
            self.audio_thread.join(timeout=2.0)

        # Le thread de capture est arrêté : la dernière image tient
        # jusqu'à cet instant, exactement comme le son est complété
        # jusqu'à maintenant dans _save_system_audio
        self._finalize_raw_video()

        if self.start_time:
            duration = (datetime.now() - self.start_time).total_seconds()
            print(f"[Lumina] Enregistrement arrêté. Durée: {duration:.2f}s, "
                  f"Frames: {self._frame_count}")
            # FPS réellement atteint : sur une machine lente la capture
            # produit moins de frames que demandé. Encoder au fps nominal
            # jouerait l'image en accéléré et la désynchroniserait du son.
            if duration > 0.5 and self._frame_count > 0:
                self.actual_fps = self._frame_count / duration

        # Le son système est exposé à part (system_audio_path) pour ne pas
        # changer le tuple de retour attendu par l'interface
        if self._system_capture is not None:
            self._system_capture.stop()
        self.system_audio_path = self._save_system_audio()

        raw_video_path = self._raw_video_path if self._frame_count > 0 else ""
        raw_audio_path = self._save_raw_audio() if self.audio_enabled else ""

        return raw_video_path, raw_audio_path

    # Qualité JPEG du flux brut. Mesuré sur cet écran : q90 = 171 Ko et
    # 7 ms par image, contre 126 Ko et 26 ms pour cv2.VideoWriter MJPG,
    # dont la qualité n'est pas réglable. Le brut est jeté après
    # encodage ; ce qui compte est qu'il n'ajoute pas d'artefacts
    # visibles à ceux du H.264 final.
    JPEG_QUALITY = 90

    def _write_frame(self, frame_bgr, t=None):
        """Applique les filtres puis place l'image dans le flux brut.

        Le flux brut est un MJPEG nu à cadence CONSTANTE (self.fps) :
        chaque image y est répétée pour tous les créneaux qu'elle a
        réellement occupés à l'écran, et une image captée avant le
        créneau suivant est simplement remplacée par la suivante.

        C'est ce qui garde la vidéo alignée sur le son quelle que soit
        la cadence de capture. Mesuré sur un enregistrement réel : la
        capture oscillait entre ~11 im/s (page statique) et ~20 im/s
        (vidéo), moyenne 17,47 ; l'ancien AVI sans horodatage, encodé à
        17 im/s constants, dérivait de 6,6 s en 44 s pendant que le son
        restait exact à 7 ms près. Un doublon coûte 0,13 ms d'écriture,
        l'image n'est encodée qu'une fois.

        `t` est l'instant réel de la capture (time.time()) ; absent,
        c'est maintenant.
        """
        frame_bgr = self.filter_chain.process(frame_bgr)
        if t is None:
            t = time.time()

        if self._raw_file is None:
            Path(self._temp_dir).mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._raw_video_path = str(
                Path(self._temp_dir) / f"lumina_raw_{timestamp}.mjpeg")
            h, w = frame_bgr.shape[:2]
            self._frame_size = (w, h)
            # Même seconde zéro que le son système (self._t0) : les
            # deux pistes partent du même instant, sans hypothèse sur
            # le délai de la première image
            self._raw_origin = self._t0 if self._t0 else t
            self._packets_written = 0
            self._last_jpg = None
            self._raw_file = open(self._raw_video_path, 'wb')

        # Une image d'une autre taille casserait le flux : on la
        # redimensionne plutôt que de la perdre. Cas légitime :
        # l'utilisateur change la résolution de son écran en cours
        # d'enregistrement. Signalé une fois — sans ce message, une
        # régression du suivi de fenêtre ne se verrait qu'à une image
        # légèrement étirée, jamais diagnostiquée.
        h, w = frame_bgr.shape[:2]
        if (w, h) != self._frame_size:
            if not self._size_mismatch_logged:
                self._size_mismatch_logged = True
                print(f"[Lumina] Taille de capture changée "
                      f"{self._frame_size} -> {(w, h)}, image redimensionnée")
            frame_bgr = cv2.resize(frame_bgr, self._frame_size,
                                   interpolation=cv2.INTER_AREA)

        ok, buf = cv2.imencode('.jpg', frame_bgr,
                               [cv2.IMWRITE_JPEG_QUALITY, self.JPEG_QUALITY])
        if not ok:
            raise RuntimeError("encodage JPEG impossible")
        jpg = buf.tobytes()

        if self._last_jpg is None:
            # La première image tient depuis l'origine : le flux ne
            # commence pas par un trou que le son n'aurait pas
            self._last_jpg = jpg
        self._flush_until(t)
        self._last_jpg = jpg
        self._frame_count += 1

    def _flush_until(self, t: float) -> None:
        """Écrit l'image courante pour chaque créneau écoulé avant t."""
        if self._raw_file is None or self._last_jpg is None:
            return
        intervalle = 1.0 / self.fps
        while self._raw_origin + self._packets_written * intervalle < t - 1e-6:
            self._raw_file.write(self._last_jpg)
            self._packets_written += 1

    def _finalize_raw_video(self, t_stop: Optional[float] = None) -> None:
        """Tient la dernière image jusqu'à l'arrêt et ferme le flux.

        Le flux dure alors exactement (t_stop - origine), comme la piste
        du son système complétée jusqu'au même instant.
        """
        if self._raw_file is None:
            return
        self._flush_until(t_stop if t_stop is not None else time.time())
        try:
            self._raw_file.close()
        finally:
            self._raw_file = None

    def _lock_smart_focus(self):
        """Verrouille le Smart Focus sur la fenêtre active, si demandé.

        L'appelant (l'interface) doit s'être effacé avant : sans cela, la
        fenêtre au premier plan serait Lumina elle-même. En cas d'échec,
        on retombe silencieusement sur l'écran entier — le Smart Focus est
        un confort, pas une condition d'enregistrement.
        """
        self._focus_tracker = None
        if not self.smart_focus_enabled:
            return

        try:
            tracker = FocusTracker(self.monitor)
            if tracker.lock_on_foreground():
                self._focus_tracker = tracker
                msg = f"Smart Focus : suivi de « {tracker.window_title} »"
            else:
                msg = "Smart Focus : aucune fenêtre détectée, écran entier"
        except Exception as e:
            msg = f"Smart Focus indisponible ({e}), écran entier"

        print(f"[Lumina] {msg}")
        if self.on_smart_focus:
            # Le callback touche l'interface : si elle vient d'être
            # détruite, son échec ne doit pas faire capoter le démarrage
            # de l'enregistrement
            try:
                self.on_smart_focus(msg)
            except Exception:
                pass

    # Nombre d'échecs de capture consécutifs tolérés avant d'abandonner.
    # BitBlt échoue temporairement dans des situations courantes et
    # passagères : session en cours de verrouillage, changement de bureau,
    # bascule d'une application en plein écran exclusif, reprise après
    # veille de l'écran. À 30 im/s, 60 échecs valent 2 secondes.
    MAX_ECHECS_CAPTURE = 60

    def _open_screen_capture(self):
        """Ouvre une session de capture d'écran.

        Point d'extension : les tests la remplacent par un double pour
        simuler un écran défaillant, sans toucher au vrai GDI.
        """
        return mss.mss()

    def _capture_screen(self):
        """Boucle de capture d'écran — écriture disque en continu.

        L'instance mss est créée ici, dans le thread qui s'en sert : sous
        Windows elle porte un contexte de périphérique GDI, et le lier au
        thread qui l'utilise évite tout partage entre threads. L'objet
        self.sct de l'initialisation ne sert qu'à lister les moniteurs.

        Une frame ratée ne met pas fin à l'enregistrement. Auparavant la
        première exception coupait tout : un échec passager de BitBlt
        (verrouillage de session, application plein écran exclusif,
        écran en veille) suffisait à perdre l'enregistrement entier, et
        c'est justement le moment où l'utilisateur ne regarde pas.
        """
        frame_interval = 1.0 / self.fps

        try:
            sct = self._open_screen_capture()
        except Exception as e:
            self.is_recording = False
            print(f"[Lumina] Capture d'écran indisponible: {e}")
            if self.on_capture_error:
                self.on_capture_error(str(e))
            return

        echecs = 0
        derniere_erreur = ""
        try:
            while self.is_recording:
                start_frame_time = time.time()

                try:
                    # Smart Focus actif : la zone suit la fenêtre verrouillée
                    region = (self._focus_tracker.current_region()
                              if self._focus_tracker else self.monitor)
                    screenshot = sct.grab(region)
                    # L'instant de l'image : celui où BitBlt vient de
                    # lire l'écran, pas celui où elle sera écrite
                    t_capture = time.time()
                    img = np.array(screenshot)
                    img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

                    self._write_frame(img_bgr, t=t_capture)
                    echecs = 0
                except Exception as e:
                    echecs += 1
                    derniere_erreur = str(e)
                    if echecs == 1:
                        # Une seule trace par épisode : à 30 im/s une
                        # panne durable noierait la console
                        print(f"[Lumina] Frame perdue ({e}), on continue")
                    if echecs >= self.MAX_ECHECS_CAPTURE:
                        self.is_recording = False
                        msg = (f"Capture d'écran interrompue après "
                               f"{echecs} échecs : {derniere_erreur}")
                        print(f"[Lumina] {msg}")
                        if self.on_capture_error:
                            self.on_capture_error(msg)
                        break
                    # Laisse passer l'incident avant de réessayer
                    time.sleep(frame_interval)
                    continue

                elapsed = time.time() - start_frame_time
                sleep_time = max(0, frame_interval - elapsed)
                time.sleep(sleep_time)
        finally:
            # Libère le contexte GDI dans le thread qui l'a créé
            try:
                sct.close()
            except Exception:
                pass
    
    def _apply_gain(self, data: bytes) -> bytes:
        """Applique le gain audio à un chunk PCM 16 bits"""
        if self.audio_gain == 1.0:
            return data
        audio_array = np.frombuffer(data, dtype=np.int16)
        audio_array = np.clip(audio_array * self.audio_gain,
                              -32768, 32767).astype(np.int16)
        return audio_array.tobytes()

    def _capture_audio(self):
        """Capture audio en mode callback.

        PortAudio pousse les chunks depuis son propre thread C : la capture
        ne dépend plus du GIL, que le thread vidéo monopolise. En mode
        bloquant, jusqu'à 75 % de l'audio était perdu par dépassement de
        buffer pendant que la vidéo occupait l'interpréteur.
        """
        p = pyaudio.PyAudio()
        stream = None

        def on_chunk(in_data, frame_count, time_info, status):
            self.audio_frames.append(self._apply_gain(in_data))
            self._audio_ready.set()   # débloque le démarrage de la vidéo
            flag = pyaudio.paContinue if self.is_recording else pyaudio.paComplete
            return (None, flag)

        try:
            stream = p.open(format=self.audio_format,
                            channels=self.channels,
                            rate=self.sample_rate,
                            input=True,
                            input_device_index=self.audio_device_index,
                            frames_per_buffer=self.chunk_size,
                            stream_callback=on_chunk)

            stream.start_stream()
            while self.is_recording and stream.is_active():
                time.sleep(0.05)
        except Exception as e:
            # La vidéo continue sans son : on prévient l'utilisateur au
            # lieu d'échouer en silence
            print(f"[Lumina] Erreur capture audio: {e}")
            if self.on_audio_error:
                self.on_audio_error(str(e))
        finally:
            # Fermer le stream avant de terminer PyAudio : un stream encore
            # actif au moment de p.terminate() est un comportement non
            # défini côté PortAudio (crash ou handle audio bloqué).
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            # Ne jamais laisser la vidéo attendre un audio qui ne viendra pas
            self._audio_ready.set()
            p.terminate()
    
    def _save_raw_audio(self) -> str:
        """Sauvegarde l'audio brut dans un fichier WAV"""
        if not self.audio_frames:
            return ""

        temp_dir = Path(self._temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        wav_path = temp_dir / f"lumina_audio_{timestamp}.wav"
        
        wf = wave.open(str(wav_path), 'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(2)  # 16 bits
        wf.setframerate(self.sample_rate)
        wf.writeframes(b''.join(self.audio_frames))
        wf.close()
        
        print(f"[Lumina] Fichier brut audio sauvegardé: {wav_path}")
        return str(wav_path)

    def _save_system_audio(self) -> str:
        """Sauvegarde le son système capté dans un WAV séparé.

        Le mixage avec le micro est délégué à FFmpeg (filtre amix) : les
        deux sources ont des fréquences différentes (44,1 kHz micro,
        48 kHz loopback) et FFmpeg rééchantillonne correctement.
        """
        if self._system_capture is None or not self._system_capture.frames:
            return ""

        temp_dir = Path(self._temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        wav_path = temp_dir / f"lumina_system_{timestamp}.wav"

        # Durée réelle de l'enregistrement : sert à combler le silence
        # final si le son s'est arrêté avant la fin de la capture
        # Même horloge que l'horodatage des chunks (self._t0)
        total = time.time() - self._t0 if self._t0 else None

        with wave.open(str(wav_path), 'wb') as wf:
            wf.setnchannels(self._system_capture.channels or 2)
            wf.setsampwidth(2)
            wf.setframerate(self._system_capture.sample_rate or 48000)
            wf.writeframes(self._system_capture.get_audio_bytes(total))

        print(f"[Lumina] Fichier brut son système sauvegardé: {wav_path}")
        return str(wav_path)


    def get_recording_duration(self) -> float:
        """Retourne la durée actuelle de l'enregistrement"""
        if not self.start_time:
            return 0.0
        return (datetime.now() - self.start_time).total_seconds()
