"""
Application d'Enregistrement d'Écran Professionnelle pour Windows
avec Système de Mise à Jour Automatique

Auteur: Assistant IA
Version: 1.0.0
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import time
import os
import sys
import json
import subprocess
import hashlib
from datetime import datetime
from pathlib import Path

# Vérification et installation des dépendances
try:
    import mss
    import mss.tools
    import numpy as np
    import cv2
    import pyaudio
    import wave
    import pyautogui
except ImportError as e:
    print(f"Installation des dépendances manquantes: {e}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "mss", "numpy", "opencv-python", "pyaudio", "pyautogui", "requests"])
    import mss
    import mss.tools
    import numpy as np
    import cv2
    import pyaudio
    import wave
    import pyautogui

try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# Configuration de l'application
APP_NAME = "ScreenRecorder Pro"
APP_VERSION = "1.0.0"
APP_AUTHOR = "Votre Nom"
CONFIG_FILE = "screen_recorder_config.json"
UPDATE_SERVER_URL = "https://raw.githubusercontent.com/votre-user/votre-repo/main/version.json"

class UpdateManager:
    """Gestionnaire de mises à jour"""
    
    def __init__(self, current_version, config_file):
        self.current_version = current_version
        self.config_file = config_file
        self.latest_version = None
        self.update_available = False
        self.update_info = {}
        
    def check_for_updates(self, callback=None):
        """Vérifie les mises à jour disponibles"""
        def check():
            try:
                # Simulation de vérification (à remplacer par votre serveur réel)
                # Pour la démo, on utilise un fichier local ou une URL GitHub
                response = requests.get(UPDATE_SERVER_URL, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    self.latest_version = data.get('version', self.current_version)
                    self.update_info = data
                    
                    # Comparaison des versions
                    if self._compare_versions(self.latest_version, self.current_version) > 0:
                        self.update_available = True
                        
                if callback:
                    callback(self.update_available, self.latest_version, self.update_info)
                    
            except Exception as e:
                print(f"Erreur lors de la vérification des mises à jour: {e}")
                if callback:
                    callback(False, None, {'error': str(e)})
        
        threading.Thread(target=check, daemon=True).start()
    
    def _compare_versions(self, v1, v2):
        """Compare deux numéros de version"""
        def normalize(v):
            return [int(x) for x in v.replace('-', '.').split('.')]
        
        v1_parts = normalize(v1)
        v2_parts = normalize(v2)
        
        for i in range(max(len(v1_parts), len(v2_parts))):
            v1_part = v1_parts[i] if i < len(v1_parts) else 0
            v2_part = v2_parts[i] if i < len(v2_parts) else 0
            
            if v1_part > v2_part:
                return 1
            elif v1_part < v2_part:
                return -1
        
        return 0
    
    def download_update(self, progress_callback=None):
        """Télécharge la mise à jour"""
        def download():
            try:
                if not self.update_info.get('download_url'):
                    raise Exception("URL de téléchargement non disponible")
                
                response = requests.get(self.update_info['download_url'], stream=True)
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                update_file = f"update_{self.latest_version}.exe"
                
                with open(update_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            if progress_callback and total_size > 0:
                                progress = (downloaded / total_size) * 100
                                progress_callback(progress)
                
                if progress_callback:
                    progress_callback(100)
                
                return update_file
                
            except Exception as e:
                if progress_callback:
                    progress_callback(-1)
                raise e
        
        return download
    
    def install_update(self, update_file):
        """Installe la mise à jour"""
        try:
            # Lance l'installateur et ferme l'application actuelle
            subprocess.Popen([update_file], cwd=os.getcwd())
            sys.exit(0)
        except Exception as e:
            raise Exception(f"Erreur lors de l'installation: {e}")


class AudioRecorder:
    """Enregistreur audio professionnel"""
    
    def __init__(self):
        self.is_recording = False
        self.audio_frames = []
        self.stream = None
        self.audio_thread = None
        self.volume_gain = 1.0
        self.sample_rate = 44100
        self.channels = 2
        self.chunk_size = 1024
        
    def start_recording(self, volume_gain=1.0):
        """Démarre l'enregistrement audio"""
        self.volume_gain = volume_gain
        self.is_recording = True
        self.audio_frames = []
        
        try:
            p = pyaudio.PyAudio()
            self.stream = p.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            
            self.audio_thread = threading.Thread(target=self._record_audio, daemon=True)
            self.audio_thread.start()
            
        except Exception as e:
            print(f"Erreur audio: {e}")
            self.is_recording = False
    
    def _record_audio(self):
        """Thread d'enregistrement audio"""
        while self.is_recording:
            try:
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                
                # Application du gain volumétrique
                if self.volume_gain != 1.0:
                    audio_data = np.frombuffer(data, dtype=np.int16)
                    audio_data = np.clip(audio_data * self.volume_gain, -32768, 32767).astype(np.int16)
                    data = audio_data.tobytes()
                
                self.audio_frames.append(data)
                
            except Exception as e:
                print(f"Erreur d'enregistrement audio: {e}")
                break
    
    def stop_recording(self, output_file):
        """Arrête l'enregistrement et sauvegarde le fichier audio"""
        self.is_recording = False
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        
        if self.audio_thread:
            self.audio_thread.join(timeout=2)
        
        # Sauvegarde du fichier WAV
        try:
            p = pyaudio.PyAudio()
            with wave.open(output_file, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
                wf.setframerate(self.sample_rate)
                wf.writeframes(b''.join(self.audio_frames))
            
            return output_file
        except Exception as e:
            print(f"Erreur de sauvegarde audio: {e}")
            return None


class ScreenRecorder:
    """Enregistreur d'écran professionnel"""
    
    def __init__(self):
        self.is_recording = False
        self.recording_thread = None
        self.frames = []
        self.fps = 30
        self.resolution = (1920, 1080)
        self.video_codec = 'mp4v'
        self.bitrate = 8000  # kbps
        
    def start_recording(self, fps=30, resolution=(1920, 1080), bitrate=8000):
        """Démarre l'enregistrement d'écran"""
        self.fps = fps
        self.resolution = resolution
        self.bitrate = bitrate
        self.is_recording = True
        self.frames = []
        
        self.recording_thread = threading.Thread(target=self._record_screen, daemon=True)
        self.recording_thread.start()
    
    def _record_screen(self):
        """Thread d'enregistrement d'écran"""
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Écran principal
            
            while self.is_recording:
                try:
                    # Capture d'écran
                    screenshot = sct.grab(monitor)
                    
                    # Conversion en format OpenCV
                    frame = np.array(screenshot)
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                    
                    # Redimensionnement si nécessaire
                    if self.resolution:
                        frame = cv2.resize(frame, self.resolution)
                    
                    self.frames.append(frame)
                    
                    # Contrôle du FPS
                    time.sleep(1.0 / self.fps)
                    
                except Exception as e:
                    print(f"Erreur de capture: {e}")
                    break
    
    def stop_recording(self, output_file, audio_file=None):
        """Arrête l'enregistrement et crée la vidéo finale"""
        self.is_recording = False
        
        if self.recording_thread:
            self.recording_thread.join(timeout=5)
        
        if not self.frames:
            return None
        
        try:
            # Création de la vidéo temporaire
            temp_video = "temp_video.avi"
            fourcc = cv2.VideoWriter_fourcc(*self.video_codec)
            out = cv2.VideoWriter(temp_video, fourcc, self.fps, self.resolution)
            
            for frame in self.frames:
                out.write(frame)
            
            out.release()
            
            # Encodage final avec FFmpeg pour une qualité optimale
            self._encode_with_ffmpeg(temp_video, output_file, audio_file)
            
            # Nettoyage
            if os.path.exists(temp_video):
                os.remove(temp_video)
            
            return output_file
            
        except Exception as e:
            print(f"Erreur de création vidéo: {e}")
            return None
    
    def _encode_with_ffmpeg(self, input_video, output_file, audio_file=None):
        """Encodage vidéo avec FFmpeg pour une qualité HD/4K optimisée"""
        try:
            # Commande FFmpeg pour un encodage haute qualité avec compression optimale
            cmd = [
                'ffmpeg', '-y',
                '-i', input_video,
                '-c:v', 'libx264',
                '-preset', 'slow',
                '-crf', '18',  # Qualité visuelle (18-28, plus bas = meilleure qualité)
                '-b:v', f'{self.bitrate}k',
                '-profile:v', 'high',
                '-level', '4.2'
            ]
            
            if audio_file and os.path.exists(audio_file):
                cmd.extend([
                    '-i', audio_file,
                    '-c:a', 'aac',
                    '-b:a', '128k',
                    '-ac', '2'
                ])
            
            cmd.append(output_file)
            
            subprocess.run(cmd, check=True, capture_output=True)
            
        except subprocess.CalledProcessError as e:
            print(f"Erreur FFmpeg: {e}")
            # Fallback vers OpenCV si FFmpeg échoue
            self._fallback_encoding(input_video, output_file, audio_file)
    
    def _fallback_encoding(self, input_video, output_file, audio_file=None):
        """Encodage de secours sans FFmpeg"""
        # Simple copie du fichier temporaire
        if os.path.exists(input_video):
            os.rename(input_video, output_file)


class ScreenRecorderApp:
    """Interface graphique principale"""
    
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("800x700")
        self.root.resizable(True, True)
        
        # Initialisation des composants
        self.recorder = ScreenRecorder()
        self.audio_recorder = AudioRecorder()
        self.update_manager = UpdateManager(APP_VERSION, CONFIG_FILE)
        
        # Variables d'état
        self.is_recording = False
        self.recording_start_time = None
        self.current_output_file = None
        self.temp_audio_file = "temp_audio.wav"
        
        # Configuration
        self.load_config()
        
        # Création de l'interface
        self.create_widgets()
        
        # Vérification des mises à jour au démarrage
        self.check_updates_on_startup()
    
    def load_config(self):
        """Charge la configuration depuis le fichier"""
        default_config = {
            'resolution': '1920x1080',
            'fps': 30,
            'bitrate': 8000,
            'volume_gain': 0.5,  # Volume bas par défaut
            'output_folder': str(Path.home() / "Videos"),
            'format': 'mp4',
            'check_updates': True
        }
        
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    default_config.update(config)
        except Exception as e:
            print(f"Erreur de chargement config: {e}")
        
        self.config = default_config
        self.save_config()
    
    def save_config(self):
        """Sauvegarde la configuration"""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Erreur de sauvegarde config: {e}")
    
    def create_widgets(self):
        """Crée l'interface utilisateur"""
        # Style
        style = ttk.Style()
        style.theme_use('clam')
        
        # Frame principale
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # En-tête
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
        title_label = ttk.Label(
            header_frame, 
            text=f"🎬 {APP_NAME}", 
            font=('Arial', 24, 'bold')
        )
        title_label.pack(side=tk.LEFT)
        
        version_label = ttk.Label(
            header_frame, 
            text=f"v{APP_VERSION}", 
            font=('Arial', 10)
        )
        version_label.pack(side=tk.RIGHT, pady=10)
        
        # Section Paramètres Vidéo
        video_frame = ttk.LabelFrame(main_frame, text="📹 Paramètres Vidéo", padding="10")
        video_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Résolution
        ttk.Label(video_frame, text="Résolution:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.resolution_var = tk.StringVar(value=self.config['resolution'])
        resolutions = [
            ('HD (1280x720)', '1280x720'),
            ('Full HD (1920x1080)', '1920x1080'),
            ('2K (2560x1440)', '2560x1440'),
            ('4K UHD (3840x2160)', '3840x2160')
        ]
        
        res_combo = ttk.Combobox(video_frame, textvariable=self.resolution_var, width=25)
        res_combo['values'] = [r[0] for r in resolutions]
        res_combo.grid(row=0, column=1, sticky=tk.W, pady=5, padx=5)
        res_combo.current([r[1] for r in resolutions].index(self.config['resolution']))
        
        # FPS
        ttk.Label(video_frame, text="FPS:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.fps_var = tk.IntVar(value=self.config['fps'])
        fps_combo = ttk.Combobox(video_frame, textvariable=self.fps_var, width=10)
        fps_combo['values'] = [24, 30, 60]
        fps_combo.grid(row=1, column=1, sticky=tk.W, pady=5, padx=5)
        
        # Bitrate
        ttk.Label(video_frame, text="Bitrate (kbps):").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.bitrate_var = tk.IntVar(value=self.config['bitrate'])
        bitrate_scale = ttk.Scale(video_frame, from_=2500, to=20000, variable=self.bitrate_var, orient=tk.HORIZONTAL)
        bitrate_scale.grid(row=2, column=1, sticky=tk.W, pady=5, padx=5)
        
        bitrate_label = ttk.Label(video_frame, textvariable=self.bitrate_var)
        bitrate_label.grid(row=2, column=2, sticky=tk.W, pady=5, padx=5)
        
        # Section Paramètres Audio
        audio_frame = ttk.LabelFrame(main_frame, text="🔊 Paramètres Audio", padding="10")
        audio_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(audio_frame, text="Volume/Gain:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.volume_var = tk.DoubleVar(value=self.config['volume_gain'])
        volume_scale = ttk.Scale(audio_frame, from_=0.1, to=2.0, variable=self.volume_var, orient=tk.HORIZONTAL)
        volume_scale.grid(row=0, column=1, sticky=tk.W, pady=5, padx=5)
        
        volume_label = ttk.Label(audio_frame, textvariable=self.volume_var)
        volume_label.grid(row=0, column=2, sticky=tk.W, pady=5, padx=5)
        
        ttk.Label(audio_frame, text="(0.5 = volume réduit de moitié)").grid(row=1, column=0, columnspan=3, sticky=tk.W, padx=5)
        
        # Section Dossier de Sortie
        output_frame = ttk.LabelFrame(main_frame, text="📁 Dossier de Sortie", padding="10")
        output_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.output_folder_var = tk.StringVar(value=self.config['output_folder'])
        ttk.Entry(output_frame, textvariable=self.output_folder_var, width=50).grid(row=0, column=0, sticky=tk.W, pady=5)
        
        ttk.Button(output_frame, text="Parcourir...", command=self.browse_folder).grid(row=0, column=1, padx=5)
        
        # Boutons de Contrôle
        control_frame = ttk.Frame(main_frame)
        control_frame.pack(fill=tk.X, pady=20)
        
        self.record_button = ttk.Button(
            control_frame, 
            text="▶️ Démarrer l'Enregistrement", 
            command=self.toggle_recording,
            style='Accent.TButton'
        )
        self.record_button.pack(side=tk.LEFT, padx=5)
        
        self.stop_button = ttk.Button(
            control_frame, 
            text="⏹️ Arrêter", 
            command=self.stop_recording,
            state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, padx=5)
        
        # Statut
        status_frame = ttk.LabelFrame(main_frame, text="📊 Statut", padding="10")
        status_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.status_var = tk.StringVar(value="Prêt à enregistrer")
        status_label = ttk.Label(status_frame, textvariable=self.status_var, font=('Arial', 11))
        status_label.pack(anchor=tk.W)
        
        self.time_var = tk.StringVar(value="00:00:00")
        time_label = ttk.Label(status_frame, textvariable=self.time_var, font=('Courier', 16, 'bold'))
        time_label.pack(anchor=tk.E, pady=10)
        
        # Barre de progression (pour les mises à jour)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(main_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        self.progress_bar.pack_forget()  # Caché par défaut
        
        # Menu
        self.create_menu()
    
    def create_menu(self):
        """Crée la barre de menu"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # Menu Fichier
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Fichier", menu=file_menu)
        file_menu.add_command(label="Ouvrir le dossier de sortie", command=self.open_output_folder)
        file_menu.add_separator()
        file_menu.add_command(label="Quitter", command=self.root.quit)
        
        # Menu Outils
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Outils", menu=tools_menu)
        tools_menu.add_command(label="Vérifier les mises à jour", command=self.manual_check_updates)
        tools_menu.add_command(label="Paramètres", command=self.show_settings)
        
        # Menu Aide
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Aide", menu=help_menu)
        help_menu.add_command(label="À propos", command=self.show_about)
    
    def toggle_recording(self):
        """Démarre ou arrête l'enregistrement"""
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()
    
    def start_recording(self):
        """Démarre l'enregistrement"""
        try:
            # Récupération des paramètres
            resolution_str = self.resolution_var.get()
            width, height = map(int, resolution_str.split('x'))
            resolution = (width, height)
            
            fps = self.fps_var.get()
            bitrate = self.bitrate_var.get()
            volume_gain = self.volume_var.get()
            
            # Génération du nom de fichier
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"recording_{timestamp}.mp4"
            output_folder = self.output_folder_var.get()
            
            # Création du dossier si nécessaire
            os.makedirs(output_folder, exist_ok=True)
            
            self.current_output_file = os.path.join(output_folder, output_filename)
            
            # Démarrage de l'enregistrement audio
            self.audio_recorder.start_recording(volume_gain=volume_gain)
            
            # Démarrage de l'enregistrement vidéo
            self.recorder.start_recording(fps=fps, resolution=resolution, bitrate=bitrate)
            
            # Mise à jour de l'interface
            self.is_recording = True
            self.recording_start_time = time.time()
            
            self.record_button.config(text="⏺️ Enregistrement en cours...")
            self.stop_button.config(state=tk.NORMAL)
            self.status_var.set(f"Enregistrement en cours → {self.current_output_file}")
            
            # Démarrage du timer
            self.update_timer()
            
            # Sauvegarde de la config
            self.config['resolution'] = resolution_str
            self.config['fps'] = fps
            self.config['bitrate'] = bitrate
            self.config['volume_gain'] = volume_gain
            self.config['output_folder'] = output_folder
            self.save_config()
            
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de démarrer l'enregistrement:\n{str(e)}")
            self.is_recording = False
    
    def stop_recording(self):
        """Arrête l'enregistrement"""
        try:
            self.is_recording = False
            
            # Arrêt de l'enregistrement audio
            audio_file = self.audio_recorder.stop_recording(self.temp_audio_file)
            
            # Arrêt de l'enregistrement vidéo et création du fichier final
            output_file = self.recorder.stop_recording(self.current_output_file, audio_file)
            
            # Nettoyage du fichier audio temporaire
            if audio_file and os.path.exists(audio_file):
                try:
                    os.remove(audio_file)
                except:
                    pass
            
            # Mise à jour de l'interface
            self.record_button.config(text="▶️ Démarrer l'Enregistrement")
            self.stop_button.config(state=tk.DISABLED)
            
            if output_file:
                self.status_var.set(f"✅ Enregistrement terminé: {output_file}")
                messagebox.showinfo("Succès", f"Vidéo enregistrée avec succès!\n\n{output_file}")
            else:
                self.status_var.set("❌ Erreur lors de l'enregistrement")
                messagebox.showerror("Erreur", "Une erreur est survenue lors de la création de la vidéo.")
            
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'arrêter l'enregistrement:\n{str(e)}")
    
    def update_timer(self):
        """Met à jour le chronomètre"""
        if self.is_recording:
            elapsed = time.time() - self.recording_start_time
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            
            self.time_var.set(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
            self.root.after(1000, self.update_timer)
        else:
            self.time_var.set("00:00:00")
    
    def browse_folder(self):
        """Ouvre le sélecteur de dossier"""
        folder = filedialog.askdirectory(initialdir=self.output_folder_var.get())
        if folder:
            self.output_folder_var.set(folder)
    
    def open_output_folder(self):
        """Ouvre le dossier de sortie"""
        folder = self.output_folder_var.get()
        if os.path.exists(folder):
            os.startfile(folder)
        else:
            messagebox.showwarning("Attention", "Le dossier de sortie n'existe pas.")
    
    def check_updates_on_startup(self):
        """Vérifie les mises à jour au démarrage"""
        if self.config.get('check_updates', True):
            self.progress_bar.pack(fill=tk.X, pady=(0, 10))
            self.progress_var.set(0)
            self.status_var.set("Vérification des mises à jour...")
            
            def on_update_check(available, version, info):
                self.progress_bar.pack_forget()
                
                if available:
                    self.show_update_dialog(version, info)
                else:
                    if 'error' not in info:
                        self.status_var.set("Prêt à enregistrer (version à jour)")
            
            self.update_manager.check_for_updates(on_update_check)
    
    def manual_check_updates(self):
        """Vérification manuelle des mises à jour"""
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        self.progress_var.set(0)
        self.status_var.set("Vérification des mises à jour...")
        
        def on_update_check(available, version, info):
            self.progress_bar.pack_forget()
            
            if available:
                self.show_update_dialog(version, info)
            else:
                if 'error' not in info:
                    messagebox.showinfo("Mises à jour", "Vous utilisez déjà la dernière version!")
                else:
                    messagebox.showerror("Erreur", f"Impossible de vérifier les mises à jour:\n{info.get('error', 'Erreur inconnue')}")
        
        self.update_manager.check_for_updates(on_update_check)
    
    def show_update_dialog(self, version, info):
        """Affiche la boîte de dialogue de mise à jour"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Mise à jour disponible!")
        dialog.geometry("500x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="🎉 Nouvelle version disponible!", font=('Arial', 16, 'bold')).pack(pady=20)
        
        details = f"""
Version actuelle: {APP_VERSION}
Nouvelle version: {version}

Changements:
{info.get('changelog', 'Améliorations diverses et corrections de bugs')}

Taille: {info.get('size', 'Inconnue')}
"""
        
        ttk.Label(dialog, text=details, justify=tk.LEFT).pack(pady=10, padx=20)
        
        def download_update():
            dialog.destroy()
            self.download_update(version, info)
        
        ttk.Button(dialog, text="Télécharger et Installer", command=download_update).pack(pady=10)
        ttk.Button(dialog, text="Plus tard", command=dialog.destroy).pack()
    
    def download_update(self, version, info):
        """Télécharge et installe la mise à jour"""
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        self.progress_var.set(0)
        self.status_var.set(f"Téléchargement de la version {version}...")
        
        download_func = self.update_manager.download_update(
            lambda progress: self.root.after(0, lambda: self.progress_var.set(progress))
        )
        
        def download_thread():
            try:
                update_file = download_func()
                
                self.root.after(0, lambda: self.status_var.set("Installation en cours..."))
                time.sleep(1)
                
                self.root.after(0, lambda: self.update_manager.install_update(update_file))
                
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Erreur", f"Échec du téléchargement:\n{str(e)}"))
                self.root.after(0, lambda: self.progress_bar.pack_forget())
        
        threading.Thread(target=download_thread, daemon=True).start()
    
    def show_settings(self):
        """Affiche les paramètres"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Paramètres")
        settings_window.geometry("400x300")
        
        ttk.Label(settings_window, text="Paramètres de l'application", font=('Arial', 14, 'bold')).pack(pady=10)
        
        # Case à cocher pour les mises à jour automatiques
        check_updates_var = tk.BooleanVar(value=self.config.get('check_updates', True))
        ttk.Checkbutton(
            settings_window, 
            text="Vérifier automatiquement les mises à jour au démarrage",
            variable=check_updates_var
        ).pack(pady=10)
        
        def save_settings():
            self.config['check_updates'] = check_updates_var.get()
            self.save_config()
            settings_window.destroy()
        
        ttk.Button(settings_window, text="Enregistrer", command=save_settings).pack(pady=20)
    
    def show_about(self):
        """Affiche la boîte de dialogue À propos"""
        about_text = f"""
{APP_NAME} v{APP_VERSION}

Application d'enregistrement d'écran professionnelle
pour Windows avec système de mise à jour automatique.

Fonctionnalités:
• Enregistrement HD, Full HD, 2K, 4K
• Contrôle précis du bitrate
• Réglage du volume audio
• Mises à jour automatiques
• Encodage optimisé H.264

Développé avec Python et Tkinter
"""
        messagebox.showinfo("À propos", about_text)


def main():
    """Point d'entrée de l'application"""
    root = tk.Tk()
    
    # Icône de l'application (optionnel)
    try:
        root.iconbitmap('icon.ico')
    except:
        pass
    
    app = ScreenRecorderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
