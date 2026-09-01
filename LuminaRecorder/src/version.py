"""Version unique de Lumina Recorder.

Seule source de vérité : le script de build la lit pour nommer le
setup NSIS et renseigner le registre Windows, l'interface l'affiche.
L'installateur compare cette valeur à celle du registre pour proposer
la mise à jour d'une installation existante.
"""

__version__ = "1.3.0"
