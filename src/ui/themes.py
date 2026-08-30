"""
Themes - Thèmes et configurations de style pour l'application
"""

from typing import Dict, Any


class AppTheme:
    """Gestion des thèmes de l'application"""
    
    # Thème sombre moderne (défaut)
    DARK_THEME = {
        'colors': {
            'bg': '#1e1e2e',         # Fond principal
            'surface': '#2a2a3e',     # Surface des cartes/panneaux
            'surface_hover': '#35354a',
            'primary': '#7c3aed',     # Violet moderne
            'primary_hover': '#6d28d9',
            'secondary': '#64748b',   # Gris bleuté
            'success': '#10b981',     # Vert
            'warning': '#f59e0b',     # Orange
            'danger': '#ef4444',      # Rouge
            'text': '#ffffff',        # Texte principal
            'text_muted': '#9ca3af',  # Texte secondaire
            'border': '#3f3f5a'       # Bordures
        },
        'fonts': {
            'title': ('Segoe UI', 24, 'bold'),
            'heading': ('Segoe UI', 14, 'bold'),
            'normal': ('Segoe UI', 10),
            'small': ('Segoe UI', 9),
            'mono': ('Consolas', 9)
        }
    }
    
    # Thème clair
    LIGHT_THEME = {
        'colors': {
            'bg': '#f8fafc',
            'surface': '#ffffff',
            'surface_hover': '#f1f5f9',
            'primary': '#7c3aed',
            'primary_hover': '#6d28d9',
            'secondary': '#64748b',
            'success': '#059669',
            'warning': '#d97706',
            'danger': '#dc2626',
            'text': '#1e293b',
            'text_muted': '#64748b',
            'border': '#e2e8f0'
        },
        'fonts': {
            'title': ('Segoe UI', 24, 'bold'),
            'heading': ('Segoe UI', 14, 'bold'),
            'normal': ('Segoe UI', 10),
            'small': ('Segoe UI', 9),
            'mono': ('Consolas', 9)
        }
    }
    
    def __init__(self, theme_name: str = 'dark'):
        self.theme_name = theme_name
        self.theme = self.DARK_THEME if theme_name == 'dark' else self.LIGHT_THEME
    
    def get_color(self, name: str) -> str:
        """Retourne la couleur demandée"""
        return self.theme['colors'].get(name, '#000000')
    
    def get_font(self, name: str) -> tuple:
        """Retourne la police demandée"""
        return self.theme['fonts'].get(name, ('Segoe UI', 10))
    
    def apply_to_widget(self, widget, element_type: str = 'label'):
        """Applique le thème à un widget"""
        colors = self.theme['colors']
        
        if element_type == 'label':
            widget.configure(
                bg=colors['bg'],
                fg=colors['text'],
                font=self.get_font('normal')
            )
        elif element_type == 'button':
            widget.configure(
                bg=colors['primary'],
                fg=colors['text'],
                font=self.get_font('normal')
            )
        elif element_type == 'card':
            widget.configure(
                bg=colors['surface'],
                highlightbackground=colors['border'],
                highlightthickness=1
            )
    
    @classmethod
    def get_all_themes(cls) -> list:
        """Retourne la liste des thèmes disponibles"""
        return ['dark', 'light']
