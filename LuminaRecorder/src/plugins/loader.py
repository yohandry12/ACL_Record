"""Chargeur de plugins et d'extensions.

Un plugin est un fichier Python déposé par l'utilisateur qui étend
Lumina sans toucher au cœur. Le même mécanisme sert aux extensions
officielles (sous-titres, OCR) installées depuis l'application.

Règle de sûreté : lister un plugin n'exécute AUCUNE de ses lignes. Les
métadonnées sont lues par analyse syntaxique ; seul un plugin
explicitement activé par l'utilisateur est importé.
"""

import ast
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Version du contrat de plugin. À incrémenter uniquement en cas de
# changement incompatible de FrameFilter ou PostProcessor : les plugins
# déclarant une version supérieure sont refusés avec un message clair
# plutôt que de planter à l'usage.
API_VERSION = 1


@dataclass
class PluginInfo:
    """Description d'un plugin, obtenue sans exécuter son code."""

    nom: str
    description: str
    auteur: str
    version: str
    api: int
    chemin: str
    identifiant: str
    erreur: str = ""

    @property
    def utilisable(self) -> bool:
        return not self.erreur


def _base_dir() -> Path:
    """Racine des données utilisateur.

    Même ancrage que get_temp_dir : hors du dossier programme, donc
    inscriptible sans droits administrateur, et préservé par une
    désinstallation de Lumina.
    """
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
        return Path(base) / 'LuminaRecorder'
    return Path.home() / '.local' / 'share' / 'lumina_recorder'


def plugins_dir() -> Path:
    """Plugins déposés par l'utilisateur."""
    return _base_dir() / 'plugins'


def extensions_dir() -> Path:
    """Modules officiels installés depuis l'application."""
    return _base_dir() / 'extensions'


def enregistrer_chemins_externes() -> None:
    """Rend les extensions importables.

    Appelé au démarrage, AVANT tout import d'easyocr ou faster_whisper :
    ces paquets ne sont plus embarqués dans l'exécutable mais installés
    à la demande dans le dossier des extensions.
    """
    dossier = extensions_dir()
    if dossier.is_dir():
        chemin = str(dossier)
        if chemin not in sys.path:
            sys.path.insert(0, chemin)


def lire_metadonnees(chemin: str) -> Optional[PluginInfo]:
    """Décrit un plugin SANS exécuter son code.

    Retourne None si le fichier n'est pas un plugin (pas de bloc
    LUMINA_PLUGIN, syntaxe invalide, illisible). Un plugin reconnu mais
    inutilisable est retourné avec son champ `erreur` renseigné : il
    doit apparaître dans l'interface avec la raison, plutôt que
    disparaître sans explication.
    """
    try:
        source = Path(chemin).read_text(encoding='utf-8')
        arbre = ast.parse(source)
    except Exception:
        return None

    brut = None
    for noeud in arbre.body:
        if not isinstance(noeud, ast.Assign):
            continue
        for cible in noeud.targets:
            if isinstance(cible, ast.Name) and cible.id == 'LUMINA_PLUGIN':
                try:
                    brut = ast.literal_eval(noeud.value)
                except Exception:
                    return None
    if not isinstance(brut, dict):
        return None

    identifiant = Path(chemin).stem
    try:
        api = int(brut.get('api', 0))
    except (TypeError, ValueError):
        api = 0

    erreur = ""
    if api > API_VERSION:
        erreur = (f"Écrit pour une version plus récente de Lumina "
                  f"(contrat {api}, cette version gère {API_VERSION})")
    elif api < 1:
        erreur = "Version du contrat manquante ou invalide"

    return PluginInfo(
        nom=str(brut.get('nom') or identifiant),
        description=str(brut.get('description') or ''),
        auteur=str(brut.get('auteur') or 'inconnu'),
        version=str(brut.get('version') or '?'),
        api=api,
        chemin=chemin,
        identifiant=identifiant,
        erreur=erreur,
    )


def lister_plugins() -> List[PluginInfo]:
    """Tous les plugins présents, utilisables ou non.

    Un dossier absent est normal — l'utilisateur n'a simplement aucun
    plugin.
    """
    trouves: List[PluginInfo] = []
    vus = set()
    for dossier in (plugins_dir(), extensions_dir()):
        try:
            if not dossier.is_dir():
                continue
            fichiers = sorted(dossier.glob('*.py'))
        except OSError:
            continue

        for fichier in fichiers:
            # __init__.py et compagnie sont de la plomberie, pas des
            # plugins
            if fichier.name.startswith('_'):
                continue
            info = lire_metadonnees(str(fichier))
            if info and info.identifiant not in vus:
                vus.add(info.identifiant)
                trouves.append(info)
    return trouves


def charger_plugin(info: PluginInfo) -> Optional[object]:
    """Importe le plugin et retourne une instance de sa classe Plugin.

    Retourne None en cas d'échec : un plugin défectueux ne doit jamais
    empêcher l'application de démarrer ni interrompre un enregistrement.
    """
    if not info.utilisable:
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            f"lumina_plugin_{info.identifiant}", info.chemin)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        classe = getattr(module, 'Plugin', None)
        if classe is None:
            print(f"[Lumina] Plugin « {info.nom} » ignoré : "
                  f"aucune classe Plugin")
            return None
        return classe()
    except Exception as e:
        print(f"[Lumina] Plugin « {info.nom} » ignoré : {e}")
        return None
