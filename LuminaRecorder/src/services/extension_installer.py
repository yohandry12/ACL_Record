"""Installation des extensions officielles.

Les fonctions lourdes (sous-titres Whisper, OCR) ne sont plus
embarquées dans l'exécutable : elles pèsent ~700 Mo pour un socle qui
en fait 250. Elles s'installent à la demande, dans le dossier des
données utilisateur — sans droits administrateur, et sans être
effacées par une désinstallation de Lumina.

Pourquoi des archives .zip et non un « pip install » : pip est absent
de l'application empaquetée (vérifié dans dist/LuminaRecorder/_internal)
et sys.executable y désigne LuminaRecorder.exe, pas un interpréteur.
Les archives sont donc préparées par le script de build, sur une
machine qui a pip, et attachées aux releases GitHub.
"""

import os
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from plugins.loader import extensions_dir

# Catalogue. `modules` sert à détecter une extension déjà installée ;
# `archive`, `url` et `taille_octets` décrivent ce qu'il faut
# récupérer. Les URL pointent sur les releases GitHub du projet, comme
# pour la mise à jour automatique.
#
# `taille_octets` est renseigné à la publication. Laissé à 0, il
# désactive le contrôle de taille de download_setup — c'est pourquoi
# l'intégrité de l'archive est vérifiée ici par testzip(), qui ne
# dépend d'aucune valeur déclarée d'avance.
DEPOT = "https://github.com/yohandry12/ACL_Record/releases/download"

EXTENSIONS: Dict[str, dict] = {
    'sous_titres': {
        'nom': "Sous-titres automatiques",
        'description': "Transcription hors ligne par Whisper",
        # Mesuré. Les deux comptent pour l'utilisateur : ce qu'il
        # télécharge, et l'espace disque qu'il y laisse ensuite.
        'taille_mo': 69,
        'disque_mo': 194,
        'modules': ['faster_whisper'],
        'version': "1.0",
        'archive': "lumina-ext-soustitres-1.0.zip",
        'url': f"{DEPOT}/ext-1.0/lumina-ext-soustitres-1.0.zip",
        'taille_octets': 72289599,
    },
    'ocr': {
        'nom': "Reconnaissance de texte",
        'description': "Flou de confidentialité et lecture du texte à l'écran",
        'taille_mo': 450,
        'modules': ['easyocr'],
        'version': "1.0",
        'archive': "lumina-ext-ocr-1.0.zip",
        'url': f"{DEPOT}/ext-1.0/lumina-ext-ocr-1.0.zip",
        'taille_octets': 0,      # renseigné à la publication
    },
}


def est_installee(cle: str) -> bool:
    """Une extension est installée si ses modules sont présents."""
    ext = EXTENSIONS.get(cle)
    if not ext:
        return False
    dossier = extensions_dir()
    return all((dossier / m).exists() for m in ext['modules'])


def extensions_manquantes() -> List[str]:
    """Clés des extensions non installées, pour le panneau Extensions."""
    return [cle for cle in EXTENSIONS if not est_installee(cle)]


def installer_extension(cle: str,
                        progress_cb: Optional[Callable[[float], None]] = None,
                        telecharger: Optional[Callable] = None) -> dict:
    """Installe une extension dans le dossier des données utilisateur.

    `telecharger` est injectable pour les tests. Aucune exception ne
    remonte : un échec produit un message affichable.
    """
    ext = EXTENSIONS.get(cle)
    if not ext:
        return {'ok': False, 'error': "Extension inconnue"}

    if est_installee(cle):
        # 450 Mo retéléchargés par inadvertance seraient impardonnables
        return {'ok': True, 'deja': True}

    dossier = extensions_dir()
    archive = None
    try:
        dossier.mkdir(parents=True, exist_ok=True)
        telecharger = telecharger or _telecharger_archive
        archive = telecharger(ext, str(dossier), progress_cb)
        _deplier(archive, dossier)
        if progress_cb:
            progress_cb(1.0)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f"Installation impossible : {e}"}
    finally:
        # L'archive ne sert plus : la garder doublerait l'espace occupé,
        # et une archive corrompue ne doit pas rester à traîner
        if archive:
            _supprimer_sans_bruit(archive)


def _deplier(archive: str, dossier: Path) -> None:
    """Extrait l'archive après en avoir vérifié l'intégrité.

    Deux contrôles avant d'écrire quoi que ce soit :

    1. `testzip` relit chaque entrée et compare son CRC. Une archive
       tronquée est ainsi rejetée entière, plutôt que dépliée à moitié
       en un module qui échouerait à l'import — bien plus difficile à
       diagnostiquer pour l'utilisateur.
    2. Aucune entrée ne doit sortir du dossier des extensions.
       Vérifié : `extractall` assainit déjà « ../ », les chemins
       absolus, UNC et « C:fichier » — tout atterrit sous la cible.
       Ce contrôle est donc une ceinture, pas la bretelle : il refuse
       l'archive au lieu de la déplier silencieusement en un
       arborescence inattendue, et il tiendra si l'extraction devient
       un jour manuelle (pour filtrer ou afficher la progression).
    """
    racine = dossier.resolve()
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError("archive corrompue")
        for membre in z.namelist():
            cible = (racine / membre).resolve()
            if cible != racine and racine not in cible.parents:
                raise RuntimeError(
                    f"entrée hors du dossier des extensions : {membre}")

        # Extraire à côté, puis basculer : une coupure pendant
        # l'extraction laisserait sinon un dossier de module à moitié
        # rempli. Mesuré : un dossier vide suffit à faire répondre
        # « installée » à est_installee ET « disponible » à find_spec —
        # l'option se dégriserait et l'échec surviendrait en plein
        # enregistrement, le pire moment possible.
        transit = racine / '.transit'
        _vider(transit)
        transit.mkdir(parents=True, exist_ok=True)
        try:
            z.extractall(transit)
            for produit in transit.iterdir():
                destination = racine / produit.name
                _vider(destination)
                os.replace(produit, destination)
        finally:
            _vider(transit)


def _vider(chemin: Path) -> None:
    """Efface un fichier ou un dossier, sans bruit s'il est absent."""
    try:
        if chemin.is_dir():
            shutil.rmtree(chemin, ignore_errors=True)
        elif chemin.exists():
            os.remove(chemin)
    except OSError:
        pass


def _telecharger_archive(ext: dict, dossier: str,
                         progress_cb=None) -> str:
    """Récupère l'archive de l'extension et retourne son chemin.

    Chaque extension est publiée comme une archive .zip attachée aux
    releases GitHub du projet, préparée par le script de build : elle
    contient les paquets déjà installés pour Windows x64 et Python
    3.11, donc rien à compiler sur la machine de l'utilisateur.

    On réutilise le téléchargement de la mise à jour automatique, qui
    gère déjà la progression, l'écriture dans un fichier .part renommé
    à la fin, et la vérification de la taille reçue.
    """
    from services.update_checker import UpdateInfo, download_setup

    info = UpdateInfo(version=ext['version'], notes='',
                      asset_url=ext['url'], asset_name=ext['archive'],
                      size=ext['taille_octets'])
    # La progression du téléchargement occupe les 95 premiers pour cent :
    # l'extraction, qui suit, n'est pas instantanée sur 450 Mo
    def avance(p):
        if progress_cb:
            progress_cb(min(0.95, p * 0.95))

    return download_setup(info, dossier, progress_cb=avance)


def desinstaller_extension(cle: str) -> dict:
    """Retire les modules d'une extension pour récupérer l'espace."""
    ext = EXTENSIONS.get(cle)
    if not ext:
        return {'ok': False, 'error': "Extension inconnue"}

    dossier = extensions_dir()
    try:
        for module in ext['modules']:
            cible = dossier / module
            if cible.is_dir():
                shutil.rmtree(cible, ignore_errors=True)
            elif cible.exists():
                _supprimer_sans_bruit(str(cible))
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': f"Suppression impossible : {e}"}


def _supprimer_sans_bruit(chemin: str) -> None:
    try:
        os.remove(chemin)
    except OSError:
        pass
