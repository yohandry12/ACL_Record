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
from core.focus_tracker import smart_focus_is_available
from core.global_hotkey import DEFAULT_HOTKEY, GlobalHotkey
from core.encoder import VideoEncoder
from core.ai_options import AIOptions
# Encore utilisé ici pour griser les cases dont le moteur est absent
from services.ocr_service import ocr_is_available
from ui.components import StyledButton, ConfigCard, StatusBadge, ResolutionSelector, VolumeSlider
from utils.config_manager import ConfigManager
from postprocess.subtitles_processor import whisper_is_available
from postprocess.base import run_postprocessors


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
        # Smart Focus : True pendant les 2 s où l'utilisateur choisit sa
        # fenêtre, fenêtre durant laquelle l'enregistrement n'a pas encore
        # démarré mais un clic ne doit pas en lancer un second
        self._focus_pending = False
        self._closing = False
        # True pendant l'encodage et le post-traitement : le raccourci
        # global n'est pas bloqué par le modal de progression
        self._busy = False
        self.hotkey = None
        
        # Construction de l'interface
        self._build_ui()

        # Après _build_ui : le raccourci écrit dans hotkey_label
        self._setup_hotkey()

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

        # Raccourci global : indispensable pour arrêter un enregistrement
        # plein écran sans faire revenir Lumina au premier plan, ce qui
        # apparaîtrait dans la vidéo. Le libellé est affiché ici pour que
        # l'utilisateur le découvre sans lire de documentation.
        self.hotkey_label = tk.Label(
            center_frame,
            text="",
            font=("Segoe UI", 9),
            bg=self.colors['bg_primary'],
            fg=self.colors['text_secondary']
        )
        self.hotkey_label.pack()

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

        # Smart Focus : n'enregistre que la fenêtre active au lieu de
        # tout l'écran. Placé ici car c'est un choix de cadrage, au même
        # titre que la résolution.
        self.smart_focus_var = tk.BooleanVar(
            value=self.config.get_bool('recording', 'smart_focus',
                                       fallback=False))
        focus_check = tk.Checkbutton(video_card,
                                     text="🎯 Smart Focus (fenêtre active)",
                                     variable=self.smart_focus_var,
                                     bg=self.colors['bg_secondary'],
                                     fg=self.colors['text_primary'],
                                     selectcolor=self.colors['bg_primary'],
                                     activebackground=self.colors['bg_secondary'],
                                     activeforeground=self.colors['text_primary'],
                                     anchor='w',
                                     font=("Segoe UI", 9, "bold"),
                                     command=self._on_smart_focus_toggled)
        if not smart_focus_is_available():
            self.smart_focus_var.set(False)
            focus_check.config(state=tk.DISABLED,
                               text="🎯 Smart Focus (installer pywin32)")
        focus_check.pack(fill=tk.X, padx=10, pady=(6, 0))

        focus_info = tk.Label(video_card,
                              text="Lumina se réduit 2 s : cliquez\n"
                                   "sur la fenêtre à enregistrer",
                              font=("Segoe UI", 8),
                              bg=self.colors['bg_secondary'],
                              fg=self.colors['text_secondary'],
                              justify=tk.LEFT)
        focus_info.pack(fill=tk.X, padx=10, pady=(0, 6))

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
            ('thumbnails', "Miniatures (3 propositions)"),
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

    def _on_smart_focus_toggled(self):
        """Persiste l'activation du Smart Focus"""
        self.config.set('recording', 'smart_focus',
                        self.smart_focus_var.get())

    def _on_smart_focus(self, message: str):
        """Appelé par le moteur : quelle fenêtre est suivie, ou l'échec."""
        self.root.after(0, lambda: self.status_label.config(
            text=message, fg=self.colors['text_secondary']))

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
        # Pendant le délai de bascule du Smart Focus, is_recording est
        # encore False : sans ce garde, un second clic lancerait un
        # DEUXIÈME enregistreur en parallèle (deux threads de capture,
        # deux flux audio sur le même micro) et le premier deviendrait
        # injoignable, son .avi jamais finalisé.
        if self._focus_pending:
            return
        # Le raccourci global contourne le modal du post-traitement :
        # grab_set() bloque la souris, pas une touche interceptée par
        # Windows. Sans ce garde, F9 pendant l'encodage lancerait un
        # enregistrement par dessus le traitement en cours.
        if self._busy:
            return
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
            system_audio_enabled=self.system_audio_var.get(),
            smart_focus_enabled=self.smart_focus_var.get(),
            on_smart_focus=self._on_smart_focus
        )

        # Smart Focus : Lumina est au premier plan au moment du clic, elle
        # se filmerait elle-même. On se réduit dans la barre des tâches et
        # on laisse 2 s à l'utilisateur pour cliquer sur sa fenêtre cible,
        # puis on verrouille dessus. Via `after` et non `sleep` : un sleep
        # gèlerait tkinter, la fenêtre ne se réduirait même pas à l'écran.
        if self.smart_focus_var.get() and smart_focus_is_available():
            self.status_label.config(
                text="🎯 Cliquez sur la fenêtre à enregistrer…",
                fg=self.colors['warning'])
            self._focus_pending = True
            self.record_btn.config(state=tk.DISABLED)
            self.root.iconify()
            self.root.after(2000,
                            lambda: self._launch_recorder(str(output_path)))
            return

        self._launch_recorder(str(output_path))

    def _launch_recorder(self, output_path: str):
        """Lance effectivement la capture et bascule l'interface.

        Séparé de `_start_recording` car le Smart Focus insère un délai
        entre la préparation et le démarrage réel.
        """
        self._focus_pending = False
        # L'utilisateur a pu fermer Lumina pendant le délai de 2 s : ce
        # callback différé toucherait alors des widgets détruits. On sort
        # sans rien démarrer plutôt que de lever une TclError et de
        # laisser un thread de capture orphelin derrière soi.
        if self._closing or not self.root.winfo_exists():
            return

        self.record_btn.config(state=tk.NORMAL)
        success = self.recorder.start_recording(output_path)

        # La fenêtre cible est verrouillée : le tracker suit ce handle et
        # plus le premier plan. Rendre Lumina visible ne détourne donc
        # plus la capture, et l'utilisateur doit pouvoir cliquer sur
        # "Arrêter" — laisser l'application réduite le priverait du seul
        # moyen d'arrêter l'enregistrement.
        if self.smart_focus_var.get() and success:
            self.root.deiconify()

        if success:
            self.is_recording = True
            self.record_btn.config(text="■ ARRÊTER L'ENREGISTREMENT",
                                  bg_color=self.colors['danger'])
            self.status_label.config(text="● Enregistrement en cours...",
                                    fg=self.colors['danger'])
            self._start_timer()
        else:
            # Restaurer l'interface réduite par le Smart Focus, sinon
            # l'utilisateur se retrouve sans fenêtre et sans explication
            self.root.deiconify()
            self.status_label.config(text="⚠ Échec du démarrage",
                                    fg=self.colors['danger'])
            
    def _stop_recording(self):
        """Logique d'arrêt d'enregistrement"""
        # Encodage puis post-traitement : le raccourci global doit rester
        # sans effet pendant tout ce temps (voir _toggle_recording).
        # Le post-traitement étant threadé, c'est _show_postprocess_summary
        # qui lève le drapeau à la toute fin ; ici on ne le lève que si
        # aucun post-traitement n'a été lancé.
        self._busy = True
        postprocessing_started = False
        try:
            postprocessing_started = bool(self._stop_recording_impl())
        finally:
            if not postprocessing_started:
                self._busy = False

    def _stop_recording_impl(self):
        """Arrêt, encodage et post-traitement proprement dits.

        Returns:
            True si un post-traitement threadé a été lancé — l'appelant
            laisse alors le drapeau _busy posé jusqu'à sa fin.
        """
        postprocessing_started = False
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
                # Par le nom sans extension : le brut est un .mjpeg, et
                # remplacer « .avi » ne changeait plus rien — le final
                # aurait écrasé le brut
                final_path = getattr(self, 'final_output_path', None) \
                    or str(Path(self.current_video_path).with_name(
                        Path(self.current_video_path).stem + '_final.mp4'))

                success = encoder.encode(
                    video_path=self.current_video_path,
                    audio_path=self.current_audio_path,
                    output_path=final_path,
                    resolution=self.resolution_combo.get().split()[0],
                    # Cadence nominale : le flux brut est déjà à cadence
                    # constante, chaque image tenue à sa place réelle
                    fps=int(getattr(self.recorder, 'fps',
                                    self.recommended_settings.get('fps', 30))),
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
                        postprocessing_started = True
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
        return postprocessing_started

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
        # Fin réelle du traitement : le raccourci global redevient actif
        self._busy = False
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
            
    def _setup_hotkey(self):
        """Active le raccourci clavier global et l'annonce à l'utilisateur.

        Un échec n'empêche jamais l'application de fonctionner : le
        raccourci est un confort, le bouton reste utilisable.
        """
        label = self.config.get('recording', 'hotkey',
                                fallback=DEFAULT_HOTKEY)
        self.hotkey = GlobalHotkey(label, on_pressed=self._on_hotkey_pressed)

        if self.hotkey.start():
            self.hotkey_label.config(
                text=f"Raccourci global : {label} "
                     f"(fonctionne même quand Lumina est en arrière-plan)")
        else:
            # Cas courant : la combinaison est déjà prise par une autre
            # application. Le dire plutôt que de laisser croire à un
            # raccourci actif qui ne répondrait jamais.
            self.hotkey_label.config(text=f"⚠ {self.hotkey.error}",
                                     fg=self.colors['warning'])

    def _on_hotkey_pressed(self):
        """Appelé depuis le thread du raccourci, pas depuis tkinter.

        On repasse par root.after : toucher un widget depuis un autre
        thread corrompt l'état interne de Tk et fait planter l'interface
        de façon aléatoire.
        """
        self.root.after(0, self._toggle_recording)

    def _on_close(self):
        """Fermeture propre de l'application.

        Arrête la capture en cours si besoin : sans cela, le thread de
        capture survit à la fenêtre et laisse un .avi jamais finalisé
        (VideoWriter.release() n'est appelé que par stop_recording).
        """
        self._closing = True
        # Libérer le raccourci : Windows le garderait pris jusqu'à la fin
        # de la session, empêchant un prochain lancement de l'obtenir
        if getattr(self, 'hotkey', None) is not None:
            self.hotkey.stop()
        if self.recorder is not None and self.recorder.is_recording:
            try:
                self.recorder.stop_recording()
            except Exception as e:
                print(f"[Lumina] Arrêt de la capture à la fermeture : {e}")
        self.root.destroy()

    def run(self):
        """Lance l'application"""
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()


if __name__ == "__main__":
    app = MainWindow()
    app.run()
