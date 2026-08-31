"""
Lumina Recorder - Main Window
Fenêtre principale de l'application avec interface utilisateur moderne.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
from datetime import datetime
from pathlib import Path

# Imports des modules locaux
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.system_analyzer import SystemAnalyzer, SystemProfile
from core.recorder_core import RecorderCore, list_input_devices, get_temp_dir
from core.system_audio import system_audio_is_available
from core.encoder import VideoEncoder
from ui.components import StyledButton, ConfigCard, StatusBadge, ResolutionSelector, VolumeSlider
from utils.config_manager import ConfigManager
from services.ocr_service import ocr_is_available
from filters.privacy_blur_filter import PrivacyBlurFilter
from filters.clean_canvas_filter import CleanCanvasFilter
from filters.overlay_filter import OverlayFilter
from postprocess.subtitles_processor import (SubtitlesProcessor,
                                             whisper_is_available)
from postprocess.magic_cut_processor import MagicCutProcessor
from postprocess.base import run_postprocessors


class AIOptions:
    """Logique des Options IA : persistance .ini et construction des
    filtres/post-processeurs. Séparée de la UI pour être testable."""

    # (clé_option) -> (section_ini, clé_ini)
    KEYS = {
        'privacy_blur': ('privacy', 'dynamic_blur'),
        'clean_canvas': ('ai', 'clean_canvas'),
        'overlay': ('system', 'show_overlay'),
        'subtitles': ('ai', 'auto_subtitles'),
        'magic_cut': ('ai', 'magic_cut'),
    }

    @staticmethod
    def load(config: ConfigManager) -> dict:
        return {opt: config.get_bool(section, key, fallback=False)
                for opt, (section, key) in AIOptions.KEYS.items()}

    @staticmethod
    def save(config: ConfigManager, options: dict) -> None:
        for opt, (section, key) in AIOptions.KEYS.items():
            config.set(section, key, options.get(opt, False))

    @staticmethod
    def build_filters(options: dict) -> list:
        filters = []
        # Sans moteur OCR, le flou n'a aucune zone à masquer : on n'ajoute
        # pas un filtre inerte, même si le .ini garde la valeur d'une
        # session où easyocr était installé
        if options.get('privacy_blur') and ocr_is_available():
            filters.append(PrivacyBlurFilter())
        if options.get('clean_canvas'):
            filters.append(CleanCanvasFilter())
        if options.get('overlay'):
            filters.append(OverlayFilter())
        return filters

    @staticmethod
    def parse_max_silence(label: str) -> float:
        """"5 s" -> 5.0 ; "Tous" -> aucune limite (tout silence est coupé)."""
        if not label or label.strip().lower() in ('tous', 'tout'):
            return float('inf')
        digits = ''.join(c for c in label if c.isdigit() or c == '.')
        try:
            return float(digits)
        except ValueError:
            return 3.0

    @staticmethod
    def build_postprocessors(options: dict,
                             max_silence: str = "3 s",
                             delete_original: bool = False) -> list:
        procs = []
        if options.get('subtitles'):
            procs.append(SubtitlesProcessor())   # sous-titres AVANT Magic Cut
        if options.get('magic_cut'):
            procs.append(MagicCutProcessor(
                max_silence_duration=AIOptions.parse_max_silence(max_silence),
                delete_original=delete_original))
        return procs


class MainWindow:
    """Fenêtre principale de l'application Lumina"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Lumina Recorder - Capturez votre monde en toute clarté")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        
        # Configuration du style
        self._setup_styles()
        
        # Analyse système au démarrage
        self.analyzer = SystemAnalyzer()
        self.recommended_settings = self.analyzer.get_recommended_settings()

        self.config = ConfigManager()
        self.ai_options = AIOptions.load(self.config)

        # Purge des .keep.wav orphelins d'une session précédente
        # interrompue (crash, fermeture pendant le post-traitement)
        self._purge_temp_files()

        # Variables d'état
        self.is_recording = False
        self.recorder = None
        self.current_video_path = None
        self.current_audio_path = None
        
        # Construction de l'interface
        self._build_ui()
        
        # Affichage du rapport système
        self._show_system_welcome()

    def _purge_temp_files(self):
        """Supprime les .keep.wav orphelins de temp/ (copies préservées
        pour un post-traitement interrompu avant nettoyage)."""
        temp_dir = get_temp_dir()
        try:
            for f in temp_dir.glob("*.keep.wav"):
                try:
                    f.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    def _setup_styles(self):
        """Configure les styles globaux"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Couleurs Lumina
        self.colors = {
            'bg_primary': '#FFFFFF',
            'bg_secondary': '#F9FAFB',
            'accent': '#4F46E5',
            'accent_hover': '#4338CA',
            'text_primary': '#1F2937',
            'text_secondary': '#6B7280',
            'success': '#059669',
            'warning': '#D97706',
            'danger': '#DC2626'
        }
        
        self.root.configure(bg=self.colors['bg_primary'])
        
    def _build_ui(self):
        """Construit l'interface utilisateur complète"""
        
        # === HEADER ===
        header_frame = tk.Frame(self.root, bg=self.colors['bg_secondary'], height=80)
        header_frame.pack(fill=tk.X, padx=0, pady=0)
        header_frame.pack_propagate(False)
        
        # Logo et titre
        logo_label = tk.Label(header_frame, text="✨ LUMINA", 
                             font=("Segoe UI", 24, "bold"),
                             bg=self.colors['bg_secondary'], 
                             fg=self.colors['accent'])
        logo_label.pack(side=tk.LEFT, padx=20, pady=20)
        
        # Badge de profil système
        profile = self.analyzer.profile.value
        self.badge = StatusBadge(header_frame, status=profile)
        self.badge.pack(side=tk.RIGHT, padx=20, pady=25)
        
        # === ZONE CENTRALE ===
        center_frame = tk.Frame(self.root, bg=self.colors['bg_primary'])
        center_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)
        
        # Bouton d'enregistrement principal
        self.record_btn = StyledButton(
            center_frame,
            text="● COMMENCER L'ENREGISTREMENT",
            command=self._toggle_recording,
            bg_color=self.colors['accent'],
            hover_color=self.colors['accent_hover']
        )
        self.record_btn.pack(pady=30, ipadx=30, ipady=15)
        
        # Label de statut
        self.status_label = tk.Label(
            center_frame,
            text="Prêt à enregistrer",
            font=("Segoe UI", 11),
            bg=self.colors['bg_primary'],
            fg=self.colors['text_secondary']
        )
        self.status_label.pack(pady=10)
        
        # Timer
        self.timer_label = tk.Label(
            center_frame,
            text="00:00:00",
            font=("Consolas", 18, "bold"),
            bg=self.colors['bg_primary'],
            fg=self.colors['text_primary']
        )
        self.timer_label.pack(pady=5)
        
        # === PANNEAU DE CONFIGURATION ===
        config_container = tk.Frame(center_frame, bg=self.colors['bg_primary'])
        config_container.pack(fill=tk.BOTH, expand=True, pady=20)
        
        # Carte 1: Qualité Vidéo
        video_card = ConfigCard(config_container, text="🎬 Qualité Vidéo")
        video_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        
        self.resolution_combo = ResolutionSelector(video_card)
        self.resolution_combo.pack(pady=10, fill=tk.X, padx=10)
        
        # Pré-remplir avec la recommandation système
        rec_res = self.recommended_settings.get('resolution', '1920x1080')
        for i, val in enumerate(self.resolution_combo['values']):
            if rec_res in val:
                self.resolution_combo.set(val)
                break
        
        rec_fps = self.recommended_settings.get('fps', 30)
        fps_label = tk.Label(video_card, 
                            text=f"FPS Recommandés: {rec_fps}",
                            font=("Segoe UI", 9),
                            bg=self.colors['bg_secondary'],
                            fg=self.colors['text_secondary'])
        fps_label.pack(pady=5)
        
        # Carte 2: Poids & Fichier
        weight_card = ConfigCard(config_container, text="⚖️ Poids & Fichier")
        weight_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        
        bitrate_label = tk.Label(weight_card, 
                                text="Bitrate (Qualité/Taille):",
                                font=("Segoe UI", 9),
                                bg=self.colors['bg_secondary'],
                                fg=self.colors['text_primary'])
        bitrate_label.pack(pady=(10,5))
        
        self.bitrate_var = tk.StringVar(value=self.recommended_settings.get('bitrate', '5000k'))
        bitrate_combo = ttk.Combobox(weight_card, textvariable=self.bitrate_var,
                                    values=["2500k", "4000k", "5000k", "6000k", 
                                           "8000k", "10000k", "15000k", "20000k"],
                                    state="readonly")
        bitrate_combo.pack(pady=5, fill=tk.X, padx=10)
        
        # Carte 3: Audio
        audio_card = ConfigCard(config_container, text="🔊 Audio (Volume Bas)")
        audio_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)
        
        # Activation du micro
        self.mic_var = tk.BooleanVar(
            value=self.config.get_bool('recording', 'audio_enabled',
                                       fallback=True))
        mic_check = tk.Checkbutton(audio_card, text="🎤 Microphone",
                                   variable=self.mic_var,
                                   bg=self.colors['bg_secondary'],
                                   fg=self.colors['text_primary'],
                                   anchor='w',
                                   font=("Segoe UI", 9, "bold"),
                                   command=self._on_mic_toggled)
        mic_check.pack(fill=tk.X, padx=5, pady=(8, 2))

        # Choix du périphérique d'entrée
        self.audio_devices = list_input_devices()
        device_labels = [self._device_label(d) for d in self.audio_devices]

        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(audio_card,
                                         textvariable=self.device_var,
                                         values=device_labels,
                                         state="readonly",
                                         font=("Segoe UI", 8))
        self.device_combo.pack(fill=tk.X, padx=5, pady=(0, 6))

        if device_labels:
            saved = self.config.get_int('recording', 'audio_device_index',
                                        fallback=-1)
            chosen = next((i for i, d in enumerate(self.audio_devices)
                           if d.index == saved), None)
            if chosen is None:
                chosen = next((i for i, d in enumerate(self.audio_devices)
                               if d.is_default), 0)
            self.device_combo.current(chosen)
            self.device_combo.bind("<<ComboboxSelected>>",
                                   self._on_device_changed)
        else:
            # Aucun micro : on le dit clairement au lieu d'un combo vide
            self.device_var.set("Aucun microphone détecté")
            self.device_combo.config(state=tk.DISABLED)
            self.mic_var.set(False)
            mic_check.config(state=tk.DISABLED)

        # Son système (loopback) : capture ce que jouent les haut-parleurs
        self.system_audio_var = tk.BooleanVar(
            value=self.config.get_bool('recording', 'system_audio',
                                       fallback=False))
        sys_check = tk.Checkbutton(audio_card, text="🔉 Son système",
                                   variable=self.system_audio_var,
                                   bg=self.colors['bg_secondary'],
                                   fg=self.colors['text_primary'],
                                   anchor='w',
                                   font=("Segoe UI", 9, "bold"),
                                   command=self._on_system_audio_toggled)
        if not system_audio_is_available():
            self.system_audio_var.set(False)
            sys_check.config(state=tk.DISABLED,
                             text="🔉 Son système (installer PyAudioWPatch)")
        sys_check.pack(fill=tk.X, padx=5, pady=(2, 6))

        audio_info = tk.Label(audio_card,
                             text="Volume de sortie (0.5x = réduit)",
                             font=("Segoe UI", 8),
                             bg=self.colors['bg_secondary'],
                             fg=self.colors['text_secondary'],
                             justify=tk.CENTER)
        audio_info.pack(pady=(4, 2))
        
        self.volume_slider = VolumeSlider(audio_card)
        self.volume_slider.pack(pady=10)

        # Carte 4: Options IA
        ai_card = ConfigCard(config_container, text="🤖 Options IA")
        ai_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)

        self.ai_vars = {}
        labels = [
            ('privacy_blur', "Flou confidentialité"),
            ('clean_canvas', "Masquer notifications"),
            ('overlay', "Overlay métriques"),
            ('subtitles', "Sous-titres auto"),
            ('magic_cut', "Couper les silences"),
        ]
        for key, label in labels:
            var = tk.BooleanVar(value=self.ai_options.get(key, False))
            if key == 'magic_cut':
                label = "Couper les silences jusqu'à"
            cb = tk.Checkbutton(ai_card, text=label, variable=var,
                                bg=self.colors['bg_secondary'],
                                fg=self.colors['text_primary'],
                                anchor='w',
                                command=self._on_ai_option_changed)
            state = tk.NORMAL
            if key == 'subtitles' and not whisper_is_available():
                state = tk.DISABLED
                cb.config(text=label + " (installer faster-whisper)")
            elif key == 'privacy_blur' and not ocr_is_available():
                state = tk.DISABLED
                var.set(False)
                cb.config(text=label + " (installer easyocr)")
            cb.config(state=state)
            cb.pack(fill=tk.X, padx=5)
            self.ai_vars[key] = var

            # Seuil de Magic Cut : figé à 3 s auparavant, ce qui protégeait
            # les longues pauses mais empêchait de supprimer les temps de
            # navigation (chercher une page, lancer une vidéo…)
            if key == 'magic_cut':
                self.magic_cut_max_var = tk.StringVar(
                    value=self.config.get('recording', 'magic_cut_max',
                                          fallback="3 s"))
                seuil = ttk.Combobox(ai_card,
                                     textvariable=self.magic_cut_max_var,
                                     values=["1 s", "2 s", "3 s", "5 s",
                                             "10 s", "30 s", "Tous"],
                                     state="readonly", width=8,
                                     font=("Segoe UI", 8))
                seuil.pack(anchor='w', padx=(24, 5), pady=(0, 0))
                tk.Label(ai_card,
                         text="(« Tous » supprime aussi les longues pauses,\n"
                              "ex. le temps de lancer une vidéo)",
                         font=("Segoe UI", 7),
                         bg=self.colors['bg_secondary'],
                         fg=self.colors['text_secondary'],
                         justify=tk.LEFT).pack(anchor='w', padx=(24, 5),
                                               pady=(0, 2))
                seuil.bind("<<ComboboxSelected>>",
                           self._on_magic_cut_max_changed)

                # Par défaut Lumina garde les deux fichiers (original +
                # version coupée) : la découpe est irréversible
                self.delete_original_var = tk.BooleanVar(
                    value=self.config.get_bool('recording',
                                               'delete_original',
                                               fallback=False))
                tk.Checkbutton(ai_card,
                               text="Supprimer l'original après découpe",
                               variable=self.delete_original_var,
                               bg=self.colors['bg_secondary'],
                               fg=self.colors['text_primary'],
                               font=("Segoe UI", 8),
                               anchor='w',
                               command=self._on_delete_original_changed
                               ).pack(fill=tk.X, padx=(24, 5), pady=(0, 4))

        # === FOOTER ===
        footer_frame = tk.Frame(self.root, bg=self.colors['bg_secondary'], height=60)
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM)
        footer_frame.pack_propagate(False)
        
        # Chemin de sauvegarde
        save_label = tk.Label(footer_frame,
                             text="📁 Dossier de sortie:",
                             font=("Segoe UI", 9),
                             bg=self.colors['bg_secondary'],
                             fg=self.colors['text_primary'])
        save_label.pack(side=tk.LEFT, padx=20, pady=15)
        
        self.save_path_var = tk.StringVar(value=str(Path.home() / "Videos" / "Lumina"))
        save_entry = tk.Entry(footer_frame, textvariable=self.save_path_var,
                             font=("Segoe UI", 9), width=50)
        save_entry.pack(side=tk.LEFT, padx=10, pady=15)
        
        browse_btn = tk.Button(footer_frame, text="Parcourir...",
                              font=("Segoe UI", 8),
                              command=self._browse_folder,
                              bg=self.colors['bg_primary'],
                              relief=tk.FLAT, cursor="hand2")
        browse_btn.pack(side=tk.LEFT, padx=10, pady=15)
        
    def _show_system_welcome(self):
        """Affiche un message de bienvenue avec le profil détecté"""
        profile = self.analyzer.profile.value
        note = self.recommended_settings.get('note', '')
        
        welcome_msg = f"""
Bienvenue dans Lumina !

Votre système a été analysé :
• Profil détecté : {profile}
• Recommandation : {note}

Les paramètres ont été automatiquement optimisés pour votre configuration.
Vous pouvez les modifier manuellement si nécessaire.
        """
        
        # Afficher dans une fenêtre modale après 500ms
        self.root.after(500, lambda: messagebox.showinfo("🚀 Lumina Prêt", welcome_msg))
        
    @staticmethod
    def _device_label(device) -> str:
        """Nom affiché d'un micro dans le sélecteur"""
        suffix = " (défaut)" if device.is_default else ""
        name = device.name if len(device.name) <= 40 else device.name[:37] + "..."
        return f"{name}{suffix}"

    def _selected_device_index(self):
        """Index PyAudio du micro choisi, None si aucun/désactivé"""
        if not self.audio_devices:
            return None
        pos = self.device_combo.current()
        if pos < 0 or pos >= len(self.audio_devices):
            return None
        return self.audio_devices[pos].index

    def _on_mic_toggled(self):
        """Persiste l'activation du micro"""
        self.config.set('recording', 'audio_enabled', self.mic_var.get())

    def _on_magic_cut_max_changed(self, event=None):
        """Persiste le seuil de coupure des silences"""
        self.config.set('recording', 'magic_cut_max',
                        self.magic_cut_max_var.get())

    def _on_delete_original_changed(self):
        """Persiste le choix de supprimer l'enregistrement complet"""
        self.config.set('recording', 'delete_original',
                        self.delete_original_var.get())

    def _on_system_audio_toggled(self):
        """Persiste l'activation du son système"""
        self.config.set('recording', 'system_audio',
                        self.system_audio_var.get())

    def _on_device_changed(self, event=None):
        """Persiste le micro choisi"""
        index = self._selected_device_index()
        if index is not None:
            self.config.set('recording', 'audio_device_index', index)

    def _on_audio_error(self, error_msg: str):
        """Appelé depuis le thread audio si le micro échoue."""
        self.root.after(0, lambda: self.status_label.config(
            text=f"⚠ Micro indisponible ({error_msg}) — vidéo sans son",
            fg=self.colors['warning']))

    def _on_ai_option_changed(self):
        """Sauvegarde immédiate des Options IA dans le .ini"""
        self.ai_options = {k: v.get() for k, v in self.ai_vars.items()}
        AIOptions.save(self.config, self.ai_options)

    def _toggle_recording(self):
        """Démarre ou arrête l'enregistrement"""
        if not self.is_recording:
            self._start_recording()
        else:
            self._stop_recording()
            
    def _start_recording(self):
        """Logique de démarrage d'enregistrement"""
        # Récupération des paramètres
        resolution_str = self.resolution_combo.get().split()[0]  # Ex: "1920x1080"
        fps = self.recommended_settings.get('fps', 30)
        audio_gain = self.volume_slider.get()
        
        # Génération du nom de fichier
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(self.save_path_var.get())
        output_dir.mkdir(parents=True, exist_ok=True)
        output_filename = f"Lumina_{timestamp}.mp4"
        output_path = output_dir / output_filename
        # Conservé pour l'encodage : le fichier final va dans le dossier
        # choisi par l'utilisateur, pas à côté du brut dans temp/
        self.final_output_path = str(output_path)

        # Préflight : FFmpeg doit être disponible AVANT de démarrer
        try:
            VideoEncoder()
        except FileNotFoundError as e:
            messagebox.showerror("FFmpeg manquant", str(e))
            return

        # Initialisation de l'enregistreur
        options = {k: v.get() for k, v in self.ai_vars.items()}
        self.recorder = RecorderCore(
            resolution=resolution_str,
            fps=fps,
            audio_enabled=self.mic_var.get(),
            audio_gain=audio_gain,
            audio_device_index=self._selected_device_index(),
            filters=AIOptions.build_filters(options),
            on_filter_disabled=self._on_filter_disabled,
            on_capture_error=self._on_capture_error,
            on_audio_error=self._on_audio_error,
            system_audio_enabled=self.system_audio_var.get()
        )

        # Démarrage
        success = self.recorder.start_recording(str(output_path))
        
        if success:
            self.is_recording = True
            self.record_btn.config(text="■ ARRÊTER L'ENREGISTREMENT",
                                  bg_color=self.colors['danger'])
            self.status_label.config(text="● Enregistrement en cours...",
                                    fg=self.colors['danger'])
            self._start_timer()
            
    def _stop_recording(self):
        """Logique d'arrêt d'enregistrement"""
        if self.recorder:
            # Arrêt de la capture
            result = self.recorder.stop_recording()
            
            if result:
                self.current_video_path, self.current_audio_path = result

                # Lancement de l'encodage
                self.status_label.config(text="⏳ Encodage en cours...")
                self.root.update()

                # Préserver le WAV pour le post-traitement (l'encodeur
                # supprime les temporaires après fusion)
                options = {k: v.get() for k, v in self.ai_vars.items()}
                needs_audio_later = options.get('subtitles') or options.get('magic_cut')
                preserved_audio = None
                if needs_audio_later and self.current_audio_path \
                        and os.path.exists(self.current_audio_path):
                    import shutil
                    preserved_audio = self.current_audio_path + ".keep.wav"
                    shutil.copyfile(self.current_audio_path, preserved_audio)

                # Encodage FFmpeg
                encoder = VideoEncoder()
                final_path = getattr(self, 'final_output_path', None) \
                    or self.current_video_path.replace('.avi', '_final.mp4')

                success = encoder.encode(
                    video_path=self.current_video_path,
                    audio_path=self.current_audio_path,
                    output_path=final_path,
                    resolution=self.resolution_combo.get().split()[0],
                    # FPS réellement atteint : encoder au fps nominal
                    # accélérerait l'image sur une machine lente
                    fps=round(getattr(self.recorder, 'actual_fps',
                                      self.recommended_settings.get('fps', 30)), 2),
                    bitrate=self.bitrate_var.get(),
                    # Le gain est déjà appliqué au WAV pendant la capture, ne pas le réappliquer ici
                    audio_gain=1.0,
                    system_audio_path=getattr(self.recorder,
                                              'system_audio_path', '')
                )

                if success:
                    self.status_label.config(text="✓ Enregistrement terminé !",
                                            fg=self.colors['success'])
                    options = {k: v.get() for k, v in self.ai_vars.items()}
                    processors = AIOptions.build_postprocessors(
                        options, self.magic_cut_max_var.get(),
                        self.delete_original_var.get())
                    if processors:
                        self._run_postprocessing(final_path, processors, preserved_audio)
                    else:
                        messagebox.showinfo(
                            "Succès", f"Vidéo sauvegardée :\n{final_path}")
                else:
                    self.status_label.config(text="✗ Erreur d'encodage",
                                            fg=self.colors['danger'])
                    if preserved_audio and os.path.exists(preserved_audio):
                        try:
                            os.remove(preserved_audio)
                        except OSError:
                            pass

        # Reset de l'état
        self.is_recording = False
        self.record_btn.config(text="● COMMENCER L'ENREGISTREMENT",
                              bg_color=self.colors['accent'])
        self.timer_label.config(text="00:00:00")

    def _run_postprocessing(self, video_path, processors, audio_path=None):
        """Exécute les post-processeurs dans un thread avec fenêtre de
        progression. La UI n'est jamais gelée ; tkinter n'est touché que
        via root.after."""
        import threading

        progress_win = tk.Toplevel(self.root)
        progress_win.title("Traitement IA en cours...")
        progress_win.geometry("400x120")
        progress_win.transient(self.root)
        progress_win.grab_set()
        progress_win.protocol("WM_DELETE_WINDOW", lambda: None)

        step_label = tk.Label(progress_win, text="Préparation...",
                              font=("Segoe UI", 10))
        step_label.pack(pady=(15, 5))
        bar = ttk.Progressbar(progress_win, maximum=1.0, length=350)
        bar.pack(pady=5)

        def on_progress(p):
            self.root.after(0, lambda: bar.config(value=p))

        def on_step(name):
            self.root.after(0, lambda: step_label.config(
                text=f"Étape : {name}..."))

        def worker():
            # Initialisé avant le try : le résumé doit s'afficher (et la
            # fenêtre de progression se fermer) même si le traitement lève
            results = []
            try:
                results = run_postprocessors(processors, video_path,
                                             audio_path, on_progress,
                                             step_cb=on_step)
            finally:
                # Dans le finally : même si run_postprocessors lève ou que
                # l'app est fermée pendant le traitement, le .keep.wav ne
                # doit pas rester dans temp/ (plusieurs centaines de Mo/h).
                if audio_path and os.path.exists(audio_path):
                    try:
                        os.remove(audio_path)  # copie .keep.wav temporaire
                    except OSError:
                        pass
                self.root.after(0, lambda: self._show_postprocess_summary(
                    video_path, results, progress_win))

        threading.Thread(target=worker, daemon=True).start()

    def _show_postprocess_summary(self, video_path, results, progress_win):
        """Résumé final : la vidéo est TOUJOURS annoncée comme sauvegardée."""
        try:
            progress_win.destroy()
        except tk.TclError:
            pass
        # L'original peut avoir été supprimé après découpe : ne pas
        # annoncer un fichier qui n'existe plus
        if os.path.exists(video_path):
            lines = [f"✓ Vidéo sauvegardée :\n{video_path}\n"]
        else:
            lines = ["✓ Enregistrement traité "
                     "(original supprimé après découpe)\n"]
        for r in results:
            if r.success and r.output_path:
                lines.append(f"✓ {r.name} : {os.path.basename(r.output_path)}")
            elif r.success:
                lines.append(f"✓ {r.name} : {r.error or 'rien à faire'}")
            else:
                lines.append(f"✗ {r.name} échoué : {r.error}")
        messagebox.showinfo("Traitement terminé", "\n".join(lines))

    def _start_timer(self):
        """Démarre le compteur de temps"""
        self.start_time = datetime.now()
        self._update_timer()
        
    def _update_timer(self):
        """Met à jour l'affichage du timer"""
        if self.is_recording:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            self.timer_label.config(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")
            self.root.after(1000, self._update_timer)
            
    def _on_filter_disabled(self, filter_name: str):
        """Appelé depuis le thread de capture quand un filtre est trop lent."""
        display = {'privacy_blur': 'Flou confidentialité',
                   'clean_canvas': 'Masquer notifications',
                   'overlay': 'Overlay métriques'}.get(filter_name,
                                                       filter_name)
        self.root.after(0, lambda: self.status_label.config(
            text=f"⚠ {display} désactivé (machine trop lente)",
            fg=self.colors['warning']))

    def _on_capture_error(self, error_msg: str):
        """Appelé depuis le thread de capture si la capture échoue."""
        def notify():
            self.status_label.config(text=f"✗ Erreur de capture : {error_msg}",
                                     fg=self.colors['danger'])
            if self.is_recording:
                self._stop_recording()
        self.root.after(0, notify)

    def _browse_folder(self):
        """Ouvre le sélecteur de dossier"""
        folder = filedialog.askdirectory(initialdir=self.save_path_var.get())
        if folder:
            self.save_path_var.set(folder)
            
    def run(self):
        """Lance l'application"""
        self.root.mainloop()


if __name__ == "__main__":
    app = MainWindow()
    app.run()
