"""Mise à jour automatique via les GitHub Releases du projet.

Principe : l'application vérifie en arrière-plan si une release plus
récente que sa propre version existe, propose de la télécharger, puis
lance le setup NSIS — qui sait déjà fermer l'application, désinstaller
l'ancienne version en silence et préserver réglages et clés API. Le
téléchargement n'exécute jamais rien tout seul : c'est l'utilisateur
qui déclenche l'installation.

La vérification est un confort, pas une condition de fonctionnement :
toute erreur (hors ligne, API indisponible, réponse malformée, aucune
release publiée) se solde par « pas de mise à jour », jamais par une
exception qui remonterait à l'interface.
"""

import os
import re
from dataclasses import dataclass
from typing import Callable, Optional

import requests

# Dépôt de distribution : les releases publiées ici portent le setup
# NSIS en pièce jointe (Lumina_Setup_x.y.z.exe, produit par le build)
GITHUB_REPO = "yohandry12/ACL_Record"
API_LATEST = "https://api.github.com/repos/{repo}/releases/latest"
TIMEOUT = 8
# Blocs de 64 Ko : assez gros pour ne pas ralentir, assez fins pour une
# progression fluide sur un setup de ~170 Mo
CHUNK = 64 * 1024


@dataclass
class UpdateInfo:
    """Une release plus récente que la version installée."""
    version: str      # « 1.2.0 », sans le préfixe v
    notes: str        # corps de la release (notes de version)
    asset_url: str    # URL de téléchargement direct du setup
    asset_name: str   # « Lumina_Setup_1.2.0.exe »
    size: int         # taille annoncée en octets, 0 si inconnue


def parse_version(text: str) -> Optional[tuple]:
    """« v1.2.0 » ou « 1.2 » -> (1, 2, 0). None si rien d'exploitable."""
    nums = re.findall(r'\d+', str(text or ''))
    if not nums:
        return None
    nums = [int(n) for n in nums[:3]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def is_newer(remote_tag: str, current_version: str) -> bool:
    """True si le tag distant est strictement plus récent.

    Un tag illisible n'est jamais « plus récent » : proposer une mise à
    jour vers une version qu'on ne sait pas comparer serait absurde.
    """
    remote = parse_version(remote_tag)
    current = parse_version(current_version)
    if remote is None or current is None:
        return False
    return remote > current


def _pick_setup_asset(assets: list) -> Optional[dict]:
    """Le setup NSIS parmi les pièces jointes de la release.

    On exige « setup » dans le nom ET l'extension .exe : la release peut
    aussi porter l'exe portable, qui n'est pas un installateur et ne
    saurait pas migrer l'installation existante.
    """
    for asset in assets or []:
        name = str(asset.get('name', ''))
        if name.lower().endswith('.exe') and 'setup' in name.lower():
            return asset
    return None


def check_for_update(current_version: str,
                     repo: str = GITHUB_REPO,
                     fetch: Optional[Callable] = None) -> Optional[UpdateInfo]:
    """Interroge GitHub et retourne la mise à jour disponible, ou None.

    `fetch` est injectable pour les tests ; par défaut requests.get.
    L'appel ne transmet aucune donnée personnelle : uniquement l'URL de
    l'API publique du dépôt.
    """
    fetch = fetch or (lambda url: requests.get(
        url, timeout=TIMEOUT,
        headers={'Accept': 'application/vnd.github+json'}))
    try:
        response = fetch(API_LATEST.format(repo=repo))
        if getattr(response, 'status_code', 0) != 200:
            return None
        data = response.json()

        tag = data.get('tag_name', '')
        if not is_newer(tag, current_version):
            return None

        asset = _pick_setup_asset(data.get('assets'))
        if asset is None:
            # Release plus récente mais sans setup : rien d'installable
            return None

        version = parse_version(tag)
        return UpdateInfo(
            version='.'.join(str(n) for n in version),
            notes=str(data.get('body') or '').strip(),
            asset_url=str(asset.get('browser_download_url', '')),
            asset_name=str(asset.get('name', '')),
            size=int(asset.get('size') or 0),
        )
    except Exception:
        # Hors ligne, quota API, JSON malformé… : pas de mise à jour
        return None


def download_setup(info: UpdateInfo, dest_dir: str,
                   progress_cb: Optional[Callable[[float], None]] = None,
                   fetch_stream: Optional[Callable] = None) -> str:
    """Télécharge le setup et retourne son chemin.

    Écrit d'abord dans un fichier .part renommé à la toute fin : un
    téléchargement interrompu ne laisse jamais un .exe incomplet qui
    ressemblerait à un installateur valide. Si la taille finale ne
    correspond pas à celle annoncée par l'API, le fichier est détruit
    et l'échec est signalé — mieux vaut pas de mise à jour qu'un
    installateur tronqué.
    """
    fetch_stream = fetch_stream or (lambda url: requests.get(
        url, timeout=TIMEOUT, stream=True))

    os.makedirs(dest_dir, exist_ok=True)
    final_path = os.path.join(dest_dir, info.asset_name)
    part_path = final_path + '.part'

    response = fetch_stream(info.asset_url)
    response.raise_for_status()

    written = 0
    try:
        with open(part_path, 'wb') as out:
            for chunk in response.iter_content(chunk_size=CHUNK):
                if not chunk:
                    continue
                out.write(chunk)
                written += len(chunk)
                if progress_cb and info.size:
                    progress_cb(min(1.0, written / info.size))
    except Exception:
        _remove_quietly(part_path)
        raise

    if info.size and written != info.size:
        _remove_quietly(part_path)
        raise RuntimeError(
            f"Téléchargement incomplet : {written} octets reçus "
            f"sur {info.size} annoncés")

    _remove_quietly(final_path)     # reliquat d'une tentative précédente
    os.replace(part_path, final_path)
    if progress_cb:
        progress_cb(1.0)
    return final_path


def _remove_quietly(path: str):
    try:
        os.remove(path)
    except OSError:
        pass
