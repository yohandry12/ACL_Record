"""Tests de l'installation des extensions.

Aucun téléchargement réel : la fonction de récupération est remplacée.
"""

import zipfile

import pytest

from services.extension_installer import (EXTENSIONS, est_installee,
                                          installer_extension,
                                          extensions_manquantes)


def test_le_catalogue_declare_les_deux_extensions():
    assert 'sous_titres' in EXTENSIONS
    assert 'ocr' in EXTENSIONS
    for cle, ext in EXTENSIONS.items():
        assert ext['modules'], f"{cle} ne déclare aucun module"
        assert ext['taille_mo'] > 0
        assert ext['url'].startswith('https://')
        assert ext['archive'].endswith('.zip')


def test_le_catalogue_annonce_des_tailles_coherentes():
    """La taille annoncée doit correspondre à l'archive publiée.

    download_setup détruit un fichier dont la taille ne correspond pas :
    une valeur erronée rendrait l'extension impossible à installer,
    après un téléchargement complet. Zéro est toléré tant que l'archive
    n'est pas publiée, mais désactive alors ce contrôle.
    """
    for cle, ext in EXTENSIONS.items():
        octets = ext['taille_octets']
        assert octets >= 0, cle
        if octets:
            annonce = ext['taille_mo'] * 1024 * 1024
            # 25 % de tolérance : « 69 Mo » affiché reste juste
            assert abs(octets - annonce) < annonce * 0.25, (
                f"{cle} : {octets} octets pour {ext['taille_mo']} Mo annoncés")
        # L'espace disque final est toujours supérieur au téléchargé
        assert ext.get('disque_mo', ext['taille_mo']) >= ext['taille_mo'], cle


def test_extension_absente_est_signalee(monkeypatch, tmp_path):
    from services import extension_installer as ei
    monkeypatch.setattr(ei, 'extensions_dir', lambda: tmp_path)

    assert est_installee('sous_titres') is False


def test_extension_presente_est_detectee(monkeypatch, tmp_path):
    from services import extension_installer as ei
    monkeypatch.setattr(ei, 'extensions_dir', lambda: tmp_path)
    (tmp_path / 'faster_whisper').mkdir()

    assert est_installee('sous_titres') is True


def test_installation_hors_ligne_echoue_proprement(monkeypatch, tmp_path):
    """Une extension qu'on ne peut pas télécharger doit produire un
    message clair, jamais une exception qui remonte à l'interface."""
    from services import extension_installer as ei
    monkeypatch.setattr(ei, 'extensions_dir', lambda: tmp_path)

    def refuse(*a, **k):
        raise ConnectionError("hors ligne")

    resultat = installer_extension('sous_titres', telecharger=refuse)

    assert resultat['ok'] is False
    assert resultat['error']


def test_un_404_est_explique_plutot_que_recopie(monkeypatch, tmp_path):
    """Vérifié dans l'interface : « 404 Client Error: Not Found for url:
    https://… » est exact mais n'indique aucune action."""
    import requests

    from services import extension_installer as ei
    monkeypatch.setattr(ei, 'extensions_dir', lambda: tmp_path)

    def introuvable(*a, **k):
        reponse = requests.Response()
        reponse.status_code = 404
        raise requests.exceptions.HTTPError(response=reponse)

    resultat = installer_extension('sous_titres', telecharger=introuvable)

    assert resultat['ok'] is False
    assert 'introuvable' in resultat['error']
    assert 'Client Error' not in resultat['error']


def test_extension_inconnue_est_refusee():
    assert installer_extension('nimporte_quoi')['ok'] is False


def test_extension_deja_installee_n_est_pas_retelechargee(monkeypatch,
                                                          tmp_path):
    """450 Mo retéléchargés par inadvertance seraient impardonnables."""
    from services import extension_installer as ei
    monkeypatch.setattr(ei, 'extensions_dir', lambda: tmp_path)
    (tmp_path / 'faster_whisper').mkdir()

    appels = []

    def compte(*a, **k):
        appels.append(1)

    resultat = installer_extension('sous_titres', telecharger=compte)

    assert resultat['ok'] is True
    assert resultat.get('deja') is True
    assert appels == [], "l'extension a été retéléchargée"


def _zip_valide(chemin, contenu=b"x = 1\n"):
    with zipfile.ZipFile(chemin, 'w') as z:
        z.writestr('faster_whisper/__init__.py', contenu)
    return chemin


def test_une_archive_valide_est_depliee(monkeypatch, tmp_path):
    from services import extension_installer as ei
    dossier = tmp_path / 'ext'
    monkeypatch.setattr(ei, 'extensions_dir', lambda: dossier)

    def livre(ext, cible, progress_cb=None):
        dossier.mkdir(parents=True, exist_ok=True)
        return str(_zip_valide(dossier / ext['archive']))

    resultat = installer_extension('sous_titres', telecharger=livre)

    assert resultat['ok'] is True, resultat.get('error')
    assert (dossier / 'faster_whisper' / '__init__.py').exists()
    assert est_installee('sous_titres') is True


def test_l_archive_est_supprimee_apres_extraction(monkeypatch, tmp_path):
    """Garder le .zip doublerait l'espace disque occupé."""
    from services import extension_installer as ei
    dossier = tmp_path / 'ext'
    monkeypatch.setattr(ei, 'extensions_dir', lambda: dossier)

    def livre(ext, cible, progress_cb=None):
        dossier.mkdir(parents=True, exist_ok=True)
        return str(_zip_valide(dossier / ext['archive']))

    installer_extension('sous_titres', telecharger=livre)

    restants = list(dossier.glob('*.zip'))
    assert restants == [], f"archive conservée : {restants}"


def test_une_archive_corrompue_ne_laisse_rien_d_installe(monkeypatch,
                                                         tmp_path):
    """Un zip tronqué déplié à moitié donnerait un module inutilisable.

    La taille annoncée ne suffit pas à s'en prémunir : le catalogue peut
    la porter à 0, ce qui désactive le contrôle de download_setup.
    """
    from services import extension_installer as ei
    dossier = tmp_path / 'ext'
    monkeypatch.setattr(ei, 'extensions_dir', lambda: dossier)

    def livre_corrompu(ext, cible, progress_cb=None):
        dossier.mkdir(parents=True, exist_ok=True)
        chemin = dossier / ext['archive']
        chemin.write_bytes(b"PK\x03\x04ceci n'est pas une archive")
        return str(chemin)

    resultat = installer_extension('sous_titres', telecharger=livre_corrompu)

    assert resultat['ok'] is False
    assert resultat['error']
    assert est_installee('sous_titres') is False
    assert list(dossier.glob('*.zip')) == [], "archive corrompue conservée"


def test_une_archive_qui_sort_du_dossier_est_refusee(monkeypatch, tmp_path):
    """Zip Slip : une entrée « ../ » doit faire refuser l'archive.

    Mesuré : extractall assainit déjà « ../ », les chemins absolus, UNC
    et « C:fichier » — rien ne sort du dossier cible. Ce test fige donc
    le refus explicite, pour qu'une archive difforme soit rejetée plutôt
    que dépliée en une arborescence inattendue.
    """
    from services import extension_installer as ei
    dossier = tmp_path / 'ext'
    monkeypatch.setattr(ei, 'extensions_dir', lambda: dossier)
    temoin = tmp_path / 'vole.txt'

    def livre_malveillant(ext, cible, progress_cb=None):
        dossier.mkdir(parents=True, exist_ok=True)
        chemin = dossier / ext['archive']
        with zipfile.ZipFile(chemin, 'w') as z:
            z.writestr('../vole.txt', 'contenu injecté')
        return str(chemin)

    resultat = installer_extension('sous_titres',
                                   telecharger=livre_malveillant)

    assert resultat['ok'] is False
    assert 'hors du dossier' in resultat['error'], resultat['error']
    assert not temoin.exists(), "écriture hors du dossier des extensions"
    # Rien ne doit avoir été déplié, pas même sous un nom assaini
    assert not (dossier / 'vole.txt').exists()


def test_une_extraction_interrompue_ne_laisse_pas_croire_a_une_install(
        monkeypatch, tmp_path):
    """Le cas le plus vicieux : une coupure pendant l'extraction.

    Mesuré : un dossier de module vide suffit à faire répondre
    « installée » à est_installee ET « disponible » à find_spec. L'option
    se dégriserait dans l'interface et l'échec surviendrait en plein
    enregistrement. L'extraction passe donc par un dossier de transit
    basculé d'un seul coup.
    """
    from services import extension_installer as ei
    dossier = tmp_path / 'ext'
    monkeypatch.setattr(ei, 'extensions_dir', lambda: dossier)

    vrai_extractall = zipfile.ZipFile.extractall

    def extraction_coupee(self, path=None, *a, **k):
        vrai_extractall(self, path, *a, **k)
        raise OSError("coupure pendant l'extraction")

    monkeypatch.setattr(zipfile.ZipFile, 'extractall', extraction_coupee)

    def livre(ext, cible, progress_cb=None):
        dossier.mkdir(parents=True, exist_ok=True)
        return str(_zip_valide(dossier / ext['archive']))

    resultat = installer_extension('sous_titres', telecharger=livre)

    assert resultat['ok'] is False
    assert est_installee('sous_titres') is False, (
        "une extraction interrompue passe pour une installation réussie")
    assert not (dossier / 'faster_whisper').exists()


def test_la_progression_atteint_cent_pour_cent(monkeypatch, tmp_path):
    from services import extension_installer as ei
    dossier = tmp_path / 'ext'
    monkeypatch.setattr(ei, 'extensions_dir', lambda: dossier)
    vus = []

    def livre(ext, cible, progress_cb=None):
        dossier.mkdir(parents=True, exist_ok=True)
        if progress_cb:
            progress_cb(0.5)
        return str(_zip_valide(dossier / ext['archive']))

    installer_extension('sous_titres', progress_cb=vus.append,
                        telecharger=livre)

    assert vus, "aucune progression rapportée"
    assert vus[-1] == 1.0
    assert all(0.0 <= v <= 1.0 for v in vus)


def test_extensions_manquantes_liste_ce_qui_reste_a_installer(monkeypatch,
                                                              tmp_path):
    from services import extension_installer as ei
    monkeypatch.setattr(ei, 'extensions_dir', lambda: tmp_path)
    (tmp_path / 'faster_whisper').mkdir()

    manquantes = extensions_manquantes()

    assert 'ocr' in manquantes
    assert 'sous_titres' not in manquantes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
