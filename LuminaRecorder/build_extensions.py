"""Prépare les archives .zip des extensions officielles.

À lancer sur la machine de build, AVANT de publier une release. Les
archives produites sont attachées à la release GitHub sous le tag que
pointe le catalogue de src/services/extension_installer.py.

Pourquoi un script et non « pip install » chez l'utilisateur : pip est
absent de l'application empaquetée, et sys.executable y désigne
LuminaRecorder.exe, pas un interpréteur. L'installation des paquets se
fait donc ici, une fois, sur une machine qui a pip.

Usage :
    python build_extensions.py              # les deux extensions
    python build_extensions.py sous_titres  # une seule
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RACINE = Path(__file__).parent
SORTIE = RACINE / 'dist_extensions'

# Paquets déjà embarqués dans l'exécutable. Les inclure dans une archive
# les ferait MASQUER ceux du socle : le dossier des extensions est placé
# en tête de sys.path par enregistrer_chemins_externes(). Deux versions
# de numpy ou de cv2 en présence, c'est au mieux du poids inutile, au
# pire une incompatibilité d'ABI au premier appel.
DEJA_EMBARQUES = [
    'numpy',
    'Pillow',
    'opencv-python-headless',
    'opencv-python',
]

# Ce que chaque extension doit installer. Les dépendances transitives
# suivent automatiquement ; seules les exclusions ci-dessus sont
# retirées ensuite.
RECETTES = {
    'sous_titres': {
        'archive': 'lumina-ext-soustitres-1.0.zip',
        'paquets': ['faster-whisper>=1.0.0'],
        # Vérifie que l'archive est utilisable avant de la publier.
        # On instancie la classe que Lumina utilise vraiment, sans
        # télécharger de modèle : un simple « import » ne dit rien des
        # imports différés, qui échouent plus tard.
        'import_test': 'faster_whisper',
        'usage_test': 'from faster_whisper import WhisperModel;'
                      ' assert WhisperModel',
    },
    'ocr': {
        'archive': 'lumina-ext-ocr-1.0.zip',
        'paquets': ['easyocr>=1.7.0'],
        'import_test': 'easyocr',
        # easyocr charge skimage en différé : l'import seul ne le
        # révèle pas. On exerce la chaîne qui a réellement cassé.
        'usage_test': 'import easyocr;'
                      ' from skimage import io;'
                      ' import numpy as np;'
                      ' assert io.imread is not None;'
                      ' assert easyocr.Reader',
    },
}


def _mo(octets: int) -> float:
    return octets / (1024 * 1024)


def _taille_dossier(chemin: Path) -> int:
    return sum(f.stat().st_size for f in chemin.rglob('*') if f.is_file())


def installer(recette: dict, cible: Path) -> None:
    """pip install --target, puis retrait de ce que le socle a déjà."""
    cible.mkdir(parents=True, exist_ok=True)
    commande = [sys.executable, '-m', 'pip', 'install',
                '--target', str(cible), '--upgrade']
    commande += recette['paquets']
    print(f"  pip install {' '.join(recette['paquets'])} …")
    resultat = subprocess.run(commande, capture_output=True, text=True)
    if resultat.returncode != 0:
        raise RuntimeError(f"pip a échoué :\n{resultat.stderr[-2000:]}")

    _retirer_doublons(cible)
    _alleger(cible)


def _retirer_doublons(cible: Path) -> None:
    """Supprime les paquets que l'exécutable embarque déjà."""
    for nom in DEJA_EMBARQUES:
        # Un paquet pip s'installe sous plusieurs noms de dossier :
        # Pillow -> PIL, opencv-python-headless -> cv2
        for motif in (nom, nom.replace('-', '_'),
                      {'Pillow': 'PIL',
                       'opencv-python-headless': 'cv2',
                       'opencv-python': 'cv2'}.get(nom, nom)):
            for chemin in list(cible.glob(f'{motif}')) + \
                          list(cible.glob(f'{motif}-*.dist-info')) + \
                          list(cible.glob(f'{motif}.libs')):
                if chemin.is_dir():
                    shutil.rmtree(chemin, ignore_errors=True)
                    print(f"    retiré (déjà dans l'exe) : {chemin.name}")
                elif chemin.exists():
                    chemin.unlink()


def _alleger(cible: Path) -> None:
    """Retire ce qui ne sert pas à l'exécution.

    Les .pyc se régénèrent, les tests et les en-têtes C ne servent qu'au
    développement. Sur PyTorch cela représente une part notable du poids.
    """
    for dossier in list(cible.rglob('__pycache__')):
        shutil.rmtree(dossier, ignore_errors=True)
    for dossier in list(cible.rglob('include')):
        # include/ de torch : en-têtes C++ inutiles à l'exécution
        if dossier.is_dir() and (dossier.parent / 'lib').exists():
            shutil.rmtree(dossier, ignore_errors=True)
    # Les .pyi ne sont PAS supprimés. Vérifié à mes dépens : scikit-image
    # les lit à l'exécution via lazy_loader, qui résout ses imports
    # différés depuis skimage/__init__.pyi. Les retirer produit une
    # archive de 604 Mo qui échoue à l'import — c'est le contrôle
    # verifier() qui l'a rattrapé avant publication.
    for motif in ('*.h', '*.hpp'):
        for fichier in cible.rglob(motif):
            try:
                fichier.unlink()
            except OSError:
                pass


def verifier(cible: Path, recette: dict) -> None:
    """Exerce le module depuis le dossier préparé, comme le fera Lumina.

    Sans ce contrôle, une archive amputée d'un fichier de trop ne se
    révélerait cassée que chez l'utilisateur, après un téléchargement de
    plusieurs centaines de mégaoctets. C'est exactement ce qui est
    arrivé : la suppression des .pyi produisait une archive OCR de
    604 Mo qui échouait à l'import de skimage.

    On va au-delà du simple import : les paquets à chargement différé
    (skimage via lazy_loader) réussissent l'import puis échouent au
    premier usage réel.
    """
    module = recette['import_test']
    usage = recette.get('usage_test') or f"import {module}"
    code = f"import sys; sys.path.insert(0, r'{cible}'); {usage}; print('OK')"
    resultat = subprocess.run([sys.executable, '-c', code],
                              capture_output=True, text=True)
    if resultat.returncode != 0:
        raise RuntimeError(
            f"l'archive est inutilisable : {module} échoue à l'usage\n"
            f"{resultat.stderr[-2000:]}")
    print(f"    usage réel de {module} : OK")


def compresser(cible: Path, archive: Path) -> None:
    print(f"  compression vers {archive.name} …")
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for fichier in sorted(cible.rglob('*')):
            if fichier.is_file():
                z.write(fichier, fichier.relative_to(cible))


def construire(cle: str) -> dict:
    recette = RECETTES[cle]
    print(f"\n=== {cle} ===")
    travail = SORTIE / f'_{cle}'
    if travail.exists():
        shutil.rmtree(travail, ignore_errors=True)

    installer(recette, travail)
    deplie = _taille_dossier(travail)
    print(f"  déplié : {_mo(deplie):.0f} Mo")

    verifier(travail, recette)

    archive = SORTIE / recette['archive']
    compresser(travail, archive)
    compresse = archive.stat().st_size
    print(f"  archive : {_mo(compresse):.0f} Mo")

    shutil.rmtree(travail, ignore_errors=True)
    return {'cle': cle, 'archive': archive.name,
            'octets': compresse, 'deplie_mo': round(_mo(deplie))}


def main() -> int:
    cles = sys.argv[1:] or list(RECETTES)
    inconnues = [c for c in cles if c not in RECETTES]
    if inconnues:
        print(f"Extension inconnue : {', '.join(inconnues)}")
        print(f"Connues : {', '.join(RECETTES)}")
        return 1

    SORTIE.mkdir(parents=True, exist_ok=True)
    resultats = []
    for cle in cles:
        try:
            resultats.append(construire(cle))
        except Exception as e:
            print(f"\nÉCHEC sur {cle} : {e}")
            return 1

    print("\n=== À reporter dans EXTENSIONS "
          "(src/services/extension_installer.py) ===")
    for r in resultats:
        print(f"  {r['cle']:12} 'taille_octets': {r['octets']},"
              f"   # {_mo(r['octets']):.0f} Mo compressés,"
              f" {r['deplie_mo']} Mo dépliés")

    ecarts = _comparer_au_catalogue(resultats)
    print(f"\nArchives dans {SORTIE}")
    if ecarts:
        print("\n!! Le catalogue ne correspond PAS aux archives produites :")
        for ligne in ecarts:
            print(f"   {ligne}")
        print("   Corriger avant de publier : download_setup détruit une")
        print("   archive dont la taille reçue diffère de celle annoncée.")
        return 1
    print("Catalogue à jour. Attacher les archives à la release GitHub")
    print("sous le tag « ext-1.0 ».")
    return 0


def _comparer_au_catalogue(resultats: list) -> list:
    """Signale tout écart entre le catalogue et les archives produites.

    Recopier les tailles à la main se désynchronise dès qu'une archive
    est reconstruite — c'est arrivé pour 58 Ko d'écart, assez pour que
    download_setup détruise le téléchargement.
    """
    try:
        sys.path.insert(0, str(RACINE / 'src'))
        from services.extension_installer import EXTENSIONS
    except Exception as e:
        return [f"catalogue illisible : {e}"]

    ecarts = []
    for r in resultats:
        annonce = EXTENSIONS.get(r['cle'], {}).get('taille_octets', 0)
        if annonce != r['octets']:
            ecarts.append(f"{r['cle']} : catalogue {annonce}, "
                          f"archive {r['octets']}")
    return ecarts


if __name__ == '__main__':
    sys.exit(main())
