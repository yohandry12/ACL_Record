"""
Lumina Recorder - Core Recording Engine
Gère la capture d'écran et audio avec optimisation selon le profil système.
"""

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


@dataclass
class AudioDevice:
    """Périphérique d'entrée audio proposé à l'utilisateur"""
    index: int
    name: str
    max_channels: int
    is_default: bool


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


def list_input_devices() -> List[AudioDevice]:
    """Liste les micros disponibles.

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

        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info.get('maxInputChannels', 0) > 0:
                devices.append(AudioDevice(
                    index=i,
                    name=_decode_device_name(
                        str(info.get('name', f'Périphérique {i}')).strip()),
                    max_channels=int(info['maxInputChannels']),
                    is_default=(i == default_index)
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
                 system_audio_enabled: bool = False):
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
        self._writer = None            # cv2.VideoWriter, ouvert à la 1re frame
        self._raw_video_path = ""
        self._frame_count = 0
        self._temp_dir = str(Path(os.getcwd()) / "temp")

        self.start_time = None
        self.output_path = None

        # Configuration MSS pour la capture d'écran
        self.sct = mss.mss()
        self.monitor = self._get_monitor_from_resolution(resolution)

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
        # Origine de temps commune à la vidéo et au son système
        self._t0 = time.time()
        self.audio_frames = []
        self._writer = None
        self._raw_video_path = ""
        self._frame_count = 0
        self.start_time = datetime.now()

        print(f"[Lumina] Démarrage de l'enregistrement : "
              f"{self.resolution} @ {self.fps} FPS")

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

        if self._writer is not None:
            self._writer.release()
            self._writer = None

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

    def _write_frame(self, frame_bgr):
        """Applique la chaîne de filtres puis écrit la frame sur disque."""
        frame_bgr = self.filter_chain.process(frame_bgr)

        if self._writer is None:
            Path(self._temp_dir).mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._raw_video_path = str(
                Path(self._temp_dir) / f"lumina_raw_{timestamp}.avi")
            h, w = frame_bgr.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            self._writer = cv2.VideoWriter(
                self._raw_video_path, fourcc, self.fps, (w, h))

        self._writer.write(frame_bgr)
        self._frame_count += 1

    def _capture_screen(self):
        """Boucle de capture d'écran — écriture disque en continu."""
        frame_interval = 1.0 / self.fps

        while self.is_recording:
            start_frame_time = time.time()

            try:
                screenshot = self.sct.grab(self.monitor)
                img = np.array(screenshot)
                img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

                self._write_frame(img_bgr)
            except Exception as e:
                self.is_recording = False
                print(f"[Lumina] Erreur capture écran: {e}")
                if self.on_capture_error:
                    self.on_capture_error(str(e))
                break

            elapsed = time.time() - start_frame_time
            sleep_time = max(0, frame_interval - elapsed)
            time.sleep(sleep_time)
    
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
        temp_dir.mkdir(exist_ok=True)

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
        temp_dir.mkdir(exist_ok=True)

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
