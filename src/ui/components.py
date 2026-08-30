"""
Components - Composants UI réutilisables
"""

import tkinter as tk
from tkinter import ttk


class StyledButton(ttk.Button):
    """Bouton stylisé avec effets modernes"""
    
    def __init__(self, parent, text="", command=None, variant='primary', **kwargs):
        style_name = f'{variant}.TButton'
        super().__init__(parent, text=text, style=style_name, command=command, **kwargs)


class QualitySelector(ttk.Combobox):
    """Sélecteur de qualité vidéo avec options prédéfinies"""
    
    QUALITY_OPTIONS = [
        "1280x720 (HD)",
        "1920x1080 (Full HD)",
        "2560x1440 (2K)",
        "3840x2160 (4K)"
    ]
    
    def __init__(self, parent, default_index=1, **kwargs):
        super().__init__(
            parent,
            values=self.QUALITY_OPTIONS,
            state="readonly",
            **kwargs
        )
        self.current(default_index)
    
    def get_resolution(self):
        """Retourne la résolution sélectionnée sous forme de tuple"""
        selected = self.get()
        if "HD" in selected and "Full" not in selected:
            return (1280, 720)
        elif "Full HD" in selected:
            return (1920, 1080)
        elif "2K" in selected:
            return (2560, 1440)
        elif "4K" in selected:
            return (3840, 2160)
        return (1920, 1080)


class VolumeSlider(ttk.Scale):
    """Curseur de volume audio avec affichage de la valeur"""
    
    def __init__(self, parent, default_value=0.5, **kwargs):
        self.value_var = tk.DoubleVar(value=default_value)
        super().__init__(
            parent,
            from_=0.1,
            to=2.0,
            variable=self.value_var,
            orient=tk.HORIZONTAL,
            **kwargs
        )
        
        # Étiquette pour afficher la valeur
        self.label = ttk.Label(
            parent,
            text=f"{default_value}x"
        )
        
        # Mise à jour dynamique de l'étiquette
        self.config(command=self._update_label)
    
    def _update_label(self, value):
        """Met à jour l'étiquette avec la valeur actuelle"""
        formatted = f"{float(value):.1f}x"
        self.label.config(text=formatted)
    
    def pack_with_label(self, **kwargs):
        """Emballe le slider avec son étiquette"""
        self.pack(side=tk.LEFT, **kwargs)
        self.label.pack(side=tk.LEFT, padx=5)
    
    def get_gain(self):
        """Retourne le gain audio actuel"""
        return self.value_var.get()
