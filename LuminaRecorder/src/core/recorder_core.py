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
from datetime import datetime
from typing import Optional, Tuple, Dict
from pathlib import Path


class RecorderCore:
    """
    Moteur principal d'enregistrement de Lumina.
    Capture vidéo (écran) et audio (micro/système) de manière synchronisée.
    """
    
    def __init__(self, resolution: str = "1920x1080", fps: int = 30, 
                 audio_enabled: bool = True, audio_gain: float = 0.5):
        self.resolution = resolution
        self.fps = fps
        self.audio_enabled = audio_enabled
        self.audio_gain = audio_gain
        
        self.is_recording = False
        self.recording_thread = None
        self.audio_thread = None
        
        self.frames = []
        self.audio_frames = []
        
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
        self.frames = []
        self.audio_frames = []
        self.start_time = datetime.now()
        
        print(f"[Lumina] Démarrage de l'enregistrement : {self.resolution} @ {self.fps} FPS")
        
        # Lancement des threads
        self.recording_thread = threading.Thread(target=self._capture_screen)
        self.recording_thread.daemon = True
        self.recording_thread.start()
        
        if self.audio_enabled:
            self.audio_thread = threading.Thread(target=self._capture_audio)
            self.audio_thread.daemon = True
            self.audio_thread.start()
            
        return True
    
    def stop_recording(self) -> Optional[str]:
        """Arrête l'enregistrement et retourne le chemin du fichier brut"""
        if not self.is_recording:
            return None
            
        self.is_recording = False
        
        # Attendre que les threads se terminent
        if self.recording_thread:
            self.recording_thread.join(timeout=2.0)
        if self.audio_thread:
            self.audio_thread.join(timeout=2.0)
            
        duration = (datetime.now() - self.start_time).total_seconds()
        print(f"[Lumina] Enregistrement arrêté. Durée: {duration:.2f}s, Frames: {len(self.frames)}")
        
        # Sauvegarde temporaire des frames bruts pour encodage ultérieur
        raw_video_path = self._save_raw_frames()
        raw_audio_path = self._save_raw_audio() if self.audio_enabled else None
        
        return raw_video_path, raw_audio_path
    
    def _capture_screen(self):
        """Boucle de capture d'écran"""
        frame_interval = 1.0 / self.fps
        
        while self.is_recording:
            start_frame_time = time.time()
            
            # Capture d'écran
            screenshot = self.sct.grab(self.monitor)
            img = np.array(screenshot)
            
            # Conversion BGRA vers BGR (OpenCV)
            img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            
            self.frames.append(img_bgr)
            
            # Contrôle du framerate
            elapsed = time.time() - start_frame_time
            sleep_time = max(0, frame_interval - elapsed)
            time.sleep(sleep_time)
    
    def _capture_audio(self):
        """Boucle de capture audio"""
        p = pyaudio.PyAudio()
        
        try:
            stream = p.open(format=self.audio_format,
                            channels=self.channels,
                            rate=self.sample_rate,
                            input=True,
                            frames_per_buffer=self.chunk_size)
            
            while self.is_recording:
                data = stream.read(self.chunk_size, exception_on_overflow=False)
                
                # Application du gain audio
                if self.audio_gain != 1.0:
                    audio_array = np.frombuffer(data, dtype=np.int16)
                    audio_array = np.clip(audio_array * self.audio_gain, -32768, 32767).astype(np.int16)
                    data = audio_array.tobytes()

                self.audio_frames.append(data)
                
            stream.stop_stream()
            stream.close()
        except Exception as e:
            print(f"[Lumina] Erreur capture audio: {e}")
        finally:
            p.terminate()
    
    def _save_raw_frames(self) -> str:
        """Sauvegarde les frames bruts dans un fichier temporaire"""
        if not self.frames:
            return ""
            
        temp_dir = Path(os.getcwd()) / "temp"
        temp_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_path = temp_dir / f"lumina_raw_{timestamp}.avi"
        
        # Écriture temporaire AVI non compressé pour vitesse
        h, w = self.frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')  # Compression légère rapide
        out = cv2.VideoWriter(str(raw_path), fourcc, self.fps, (w, h))
        
        for frame in self.frames:
            out.write(frame)
            
        out.release()
        print(f"[Lumina] Fichier brut vidéo sauvegardé: {raw_path}")
        return str(raw_path)
    
    def _save_raw_audio(self) -> str:
        """Sauvegarde l'audio brut dans un fichier WAV"""
        if not self.audio_frames:
            return ""
            
        temp_dir = Path(os.getcwd()) / "temp"
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
    
    def get_recording_duration(self) -> float:
        """Retourne la durée actuelle de l'enregistrement"""
        if not self.start_time:
            return 0.0
        return (datetime.now() - self.start_time).total_seconds()
