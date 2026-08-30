"""
MainWindow - Fenêtre principale de l'application
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional


class MainWindow:
    """Fenêtre principale de l'application avec design moderne"""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ScreenRecorder Pro")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        
        # Style moderne
        self._setup_styles()
        
        # Variables d'état
        self.is_recording = False
        
        # Création de l'interface
        self._create_ui()
    
    def _setup_styles(self):
        """Configure les styles modernes pour l'interface"""
        style = ttk.Style()
        
        # Thème de base
        style.theme_use('clam')
        
        # Couleurs modernes
        colors = {
            'bg': '#1e1e2e',      # Fond sombre
            'surface': '#2a2a3e',  # Surface des cartes
            'primary': '#7c3aed',  # Violet moderne
            'success': '#10b981',  # Vert
            'danger': '#ef4444',   # Rouge
            'text': '#ffffff',
            'text_muted': '#9ca3af'
        }
        
        # Configuration du style global
        self.root.configure(bg=colors['bg'])
        
        # Styles pour les boutons
        style.configure('Primary.TButton',
                       background=colors['primary'],
                       foreground='white',
                       font=('Segoe UI', 10, 'bold'),
                       padding=10)
        
        style.map('Primary.TButton',
                 background=[('active', '#6d28d9')])
    
    def _create_ui(self):
        """Crée l'interface utilisateur principale"""
        # Frame principale
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # En-tête
        self._create_header(main_frame)
        
        # Section analyse système
        self._create_system_info_section(main_frame)
        
        # Section paramètres
        self._create_settings_section(main_frame)
        
        # Section contrôles d'enregistrement
        self._create_controls_section(main_frame)
        
        # Barre d'état
        self._create_status_bar(main_frame)
    
    def _create_header(self, parent):
        """Crée l'en-tête de l'application"""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
        title_label = ttk.Label(
            header_frame,
            text="🎬 ScreenRecorder Pro",
            font=('Segoe UI', 24, 'bold')
        )
        title_label.pack(side=tk.LEFT)
        
        version_label = ttk.Label(
            header_frame,
            text="v1.0.0",
            font=('Segoe UI', 9),
            foreground='#9ca3af'
        )
        version_label.pack(side=tk.RIGHT, pady=10)
    
    def _create_system_info_section(self, parent):
        """Crée la section d'information système"""
        info_frame = ttk.LabelFrame(
            parent,
            text="📊 Analyse Système",
            padding="15"
        )
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Badge de niveau système
        tier_frame = ttk.Frame(info_frame)
        tier_frame.pack(fill=tk.X)
        
        self.tier_label = ttk.Label(
            tier_frame,
            text="Niveau: DÉTECTION EN COURS...",
            font=('Segoe UI', 11, 'bold')
        )
        self.tier_label.pack(side=tk.LEFT)
        
        # Bouton pour rafraîchir l'analyse
        refresh_btn = ttk.Button(
            tier_frame,
            text="🔄 Analyser",
            command=self._refresh_system_analysis
        )
        refresh_btn.pack(side=tk.RIGHT)
    
    def _create_settings_section(self, parent):
        """Crée la section des paramètres d'enregistrement"""
        settings_frame = ttk.LabelFrame(
            parent,
            text="⚙️ Paramètres d'Enregistrement",
            padding="15"
        )
        settings_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Grille pour les paramètres
        grid_frame = ttk.Frame(settings_frame)
        grid_frame.pack(fill=tk.BOTH, expand=True)
        
        # Résolution
        ttk.Label(grid_frame, text="Résolution:").grid(row=0, column=0, sticky='w', pady=5)
        self.resolution_var = tk.StringVar(value="1920x1080 (Full HD)")
        resolution_combo = ttk.Combobox(
            grid_frame,
            textvariable=self.resolution_var,
            values=[
                "1280x720 (HD)",
                "1920x1080 (Full HD)",
                "2560x1440 (2K)",
                "3840x2160 (4K)"
            ],
            state="readonly",
            width=30
        )
        resolution_combo.grid(row=0, column=1, padx=10, pady=5)
        
        # FPS
        ttk.Label(grid_frame, text="FPS:").grid(row=1, column=0, sticky='w', pady=5)
        self.fps_var = tk.StringVar(value="30")
        fps_combo = ttk.Combobox(
            grid_frame,
            textvariable=self.fps_var,
            values=["24", "30", "60"],
            state="readonly",
            width=30
        )
        fps_combo.grid(row=1, column=1, padx=10, pady=5)
        
        # Bitrate
        ttk.Label(grid_frame, text="Bitrate:").grid(row=2, column=0, sticky='w', pady=5)
        self.bitrate_var = tk.StringVar(value="5000k")
        bitrate_combo = ttk.Combobox(
            grid_frame,
            textvariable=self.bitrate_var,
            values=[
                "2500k (Léger)",
                "5000k (Standard)",
                "8000k (Qualité)",
                "15000k (Ultra)",
                "20000k (Maximum)"
            ],
            state="readonly",
            width=30
        )
        bitrate_combo.grid(row=2, column=1, padx=10, pady=5)
        
        # Volume audio
        ttk.Label(grid_frame, text="Volume Audio:").grid(row=3, column=0, sticky='w', pady=5)
        self.volume_var = tk.DoubleVar(value=0.5)
        volume_scale = ttk.Scale(
            grid_frame,
            from_=0.1,
            to=2.0,
            variable=self.volume_var,
            orient=tk.HORIZONTAL,
            length=200
        )
        volume_scale.grid(row=3, column=1, padx=10, pady=5, sticky='w')
        
        volume_label = ttk.Label(
            grid_frame,
            text="0.5x (Recommandé)"
        )
        volume_label.grid(row=3, column=2, padx=5, pady=5)
    
    def _create_controls_section(self, parent):
        """Crée la section des contrôles d'enregistrement"""
        controls_frame = ttk.Frame(parent)
        controls_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Bouton d'enregistrement principal
        self.record_btn = ttk.Button(
            controls_frame,
            text="▶️ Démarrer l'Enregistrement",
            style='Primary.TButton',
            command=self._toggle_recording
        )
        self.record_btn.pack(side=tk.LEFT, padx=5)
        
        # Bouton d'arrêt (désactivé par défaut)
        self.stop_btn = ttk.Button(
            controls_frame,
            text="⏹️ Arrêter",
            state='disabled',
            command=self._stop_recording
        )
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        # Sélecteur de dossier
        folder_frame = ttk.Frame(controls_frame)
        folder_frame.pack(side=tk.RIGHT)
        
        ttk.Label(folder_frame, text="Dossier de sortie:").pack(side=tk.LEFT, padx=5)
        
        self.folder_var = tk.StringVar(value="C:/Videos")
        folder_entry = ttk.Entry(folder_frame, textvariable=self.folder_var, width=30)
        folder_entry.pack(side=tk.LEFT, padx=5)
        
        browse_btn = ttk.Button(
            folder_frame,
            text="Parcourir",
            command=self._browse_folder
        )
        browse_btn.pack(side=tk.LEFT)
    
    def _create_status_bar(self, parent):
        """Crée la barre d'état en bas"""
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.status_label = ttk.Label(
            status_frame,
            text="✅ Prêt à enregistrer",
            font=('Segoe UI', 9)
        )
        self.status_label.pack(side=tk.LEFT)
        
        self.usage_label = ttk.Label(
            status_frame,
            text="CPU: 0% | RAM: 0%",
            font=('Segoe UI', 9),
            foreground='#9ca3af'
        )
        self.usage_label.pack(side=tk.RIGHT)
    
    def _refresh_system_analysis(self):
        """Rafraîchit l'analyse du système"""
        # TODO: Appeler SystemAnalyzer et mettre à jour l'UI
        self.tier_label.config(text="Niveau: STANDARD (Détection automatique)")
        self.status_label.config(text="🔄 Analyse système terminée")
    
    def _toggle_recording(self):
        """Basculer l'état d'enregistrement"""
        if not self.is_recording:
            self.is_recording = True
            self.record_btn.config(text="🔴 Enregistrement en cours...")
            self.stop_btn.config(state='normal')
            self.status_label.config(text="🔴 Enregistrement en cours...")
        else:
            self.is_recording = False
            self.record_btn.config(text="▶️ Démarrer l'Enregistrement")
            self.stop_btn.config(state='disabled')
            self.status_label.config(text="✅ Enregistrement terminé")
    
    def _stop_recording(self):
        """Arrête l'enregistrement"""
        self.is_recording = False
        self.record_btn.config(text="▶️ Démarrer l'Enregistrement")
        self.stop_btn.config(state='disabled')
        self.status_label.config(text="✅ Enregistrement sauvegardé")
    
    def _browse_folder(self):
        """Ouvre le sélecteur de dossier"""
        # TODO: Implémenter avec filedialog
        pass
