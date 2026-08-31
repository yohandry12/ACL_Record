"""
Lumina Recorder - UI Components
Composants réutilisables pour l'interface utilisateur.
"""

try:
    import tkinter as tk
    from tkinter import ttk
    CUSTOM_TK_AVAILABLE = False
except ImportError:
    # Fallback si customtkinter n'est pas installé
    import tkinter as tk
    from tkinter import ttk
    CUSTOM_TK_AVAILABLE = False

# Tentative d'import de CustomTkinter pour un design moderne
if CUSTOM_TK_AVAILABLE:
    try:
        import customtkinter as ctk
        CUSTOM_TK_AVAILABLE = True
    except ImportError:
        CUSTOM_TK_AVAILABLE = False


class StyledButton(tk.Button):
    """Bouton stylisé avec effets hover"""
    
    def __init__(self, master, text, command=None, bg_color="#4F46E5", 
                 fg_color="#FFFFFF", hover_color="#4338CA", **kwargs):
        super().__init__(master, text=text, command=command,
                        bg=bg_color, fg=fg_color,
                        activebackground=hover_color,
                        activeforeground=fg_color,
                        relief=tk.FLAT, padx=20, pady=10,
                        font=("Segoe UI", 12, "bold"),
                        cursor="hand2", **kwargs)
        
        self.default_bg = bg_color
        self.hover_bg = hover_color
        
        self.bind("<Enter>", self._on_hover)
        self.bind("<Leave>", self._on_leave)
        
    def config(self, cnf=None, **kwargs):
        # bg_color/hover_color ne sont pas des options tkinter : on les
        # traduit et on met à jour l'état hover pour que _on_leave ne
        # restaure pas l'ancienne couleur
        bg_color = kwargs.pop('bg_color', None)
        hover_color = kwargs.pop('hover_color', None)
        if bg_color is not None:
            self.default_bg = bg_color
            kwargs['bg'] = bg_color
        if hover_color is not None:
            self.hover_bg = hover_color
            kwargs['activebackground'] = hover_color
        return super().config(cnf, **kwargs)

    configure = config

    def _on_hover(self, event):
        super().config(bg=self.hover_bg)

    def _on_leave(self, event):
        super().config(bg=self.default_bg)


class ConfigCard(tk.LabelFrame):
    """Carte de configuration avec titre et contenu"""
    
    def __init__(self, master, text="", **kwargs):
        super().__init__(master, text=text, padx=15, pady=15,
                        font=("Segoe UI", 10, "bold"),
                        relief=tk.GROOVE, borderwidth=2, **kwargs)
        
        self.configure(bg="#F9FAFB", fg="#1F2937")


class StatusBadge(tk.Label):
    """Badge d'état (Entry/Standard/Pro)"""
    
    def __init__(self, master, status="STANDARD", **kwargs):
        colors = {
            "ENTRY": {"bg": "#FEE2E2", "fg": "#DC2626"},      # Rouge doux
            "STANDARD": {"bg": "#DBEAFE", "fg": "#2563EB"},   # Bleu
            "PRO": {"bg": "#D1FAE5", "fg": "#059669"}         # Vert
        }
        
        color_scheme = colors.get(status, colors["STANDARD"])
        
        super().__init__(master, text=f"● {status}", 
                        bg=color_scheme["bg"], fg=color_scheme["fg"],
                        font=("Segoe UI", 9, "bold"),
                        padx=10, pady=5, relief=tk.FLAT, **kwargs)


class ResolutionSelector(ttk.Combobox):
    """Sélecteur de résolution avec valeurs prédéfinies"""
    
    def __init__(self, master, **kwargs):
        values = [
            "1280x720 (HD)",
            "1920x1080 (Full HD)",
            "2560x1440 (2K)",
            "3840x2160 (4K UHD)"
        ]
        
        super().__init__(master, values=values, state="readonly", **kwargs)
        self.set("1920x1080 (Full HD)")


class VolumeSlider(tk.Scale):
    """Curseur de volume avec graduation"""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, from_=0.1, to=2.0, resolution=0.1,
                        orient=tk.HORIZONTAL, length=200,
                        tickinterval=0.5, font=("Segoe UI", 9),
                        bg="#F9FAFB", fg="#1F2937",
                        troughcolor="#E5E7EB", **kwargs)
        self.set(0.5)  # Valeur par défaut: volume bas
