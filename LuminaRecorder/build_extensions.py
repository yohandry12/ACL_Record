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
        # Vérifie que l'archive est utilisable avant de la publier
        'import_test': 'faster_whisper',
    },
    'ocr': {
        'archive': 'lumina-ext-ocr-1.0.zip',
        'paquets': ['easyocr>=1.7.0'],
        'import_test': 'easyocr',
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
    for motif in ('*.pyi', '*.h', '*.hpp'):
        for fichier in cible.rglob(motif):
            try:
                fichier.unlink()
            except OSError:
                pass


def verifier(cible: Path, module: str) -> None:
    """Importe le module depuis le dossier préparé, comme le fera Lumina.

    Sans ce contrôle, une archive amputée d'un doublon de trop ne se
    révélerait cassée que chez l'utilisateur, après un téléchargement de
    plusieurs centaines de mégaoctets.
    """
    code = (f"import sys; sys.path.insert(0, r'{cible}');"
            f" import {module}; print({module}.__name__, 'OK')")
    resultat = subprocess.run([sys.executable, '-c', code],
                              capture_output=True, text=True)
    if resultat.returncode != 0:
        raise RuntimeError(
            f"l'archive est inutilisable : import {module} échoue\n"
            f"{resultat.stderr[-2000:]}")
    print(f"    import {module} : OK")


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

    verifier(travail, recette['import_test'])

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
    print(f"\nArchives dans {SORTIE}")
    print("Les attacher à la release GitHub sous le tag « ext-1.0 ».")
    return 0


if __name__ == '__main__':
    sys.exit(main())
