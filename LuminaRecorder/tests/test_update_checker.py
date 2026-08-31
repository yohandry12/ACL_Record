"""Tests de la mise à jour automatique (GitHub Releases).

Aucun appel réseau : les fonctions de récupération sont remplacées par
des doubles, y compris défaillants — une mise à jour ne doit jamais
casser l'application qui la cherche.
"""

import pytest

from services.update_checker import (UpdateInfo, check_for_update,
                                     download_setup, is_newer,
                                     parse_version)


# --- comparaison de versions ---

def test_version_distante_plus_recente():
    assert is_newer("v1.2.0", "1.1.0") is True


def test_meme_version_n_est_pas_une_mise_a_jour():
    assert is_newer("v1.1.0", "1.1.0") is False


def test_version_distante_plus_ancienne():
    assert is_newer("v1.0.9", "1.1.0") is False


def test_prefixe_v_et_composants_manquants():
    """« v1.2 » vaut « 1.2.0 » : les tags courts sont fréquents."""
    assert parse_version("v1.2") == (1, 2, 0)
    assert is_newer("1.1.1", "v1.1") is True


def test_tag_illisible_n_est_jamais_plus_recent():
    """Proposer une mise à jour vers une version incomparable serait
    absurde : dans le doute, on se tait."""
    assert is_newer("beta", "1.1.0") is False
    assert is_newer("", "1.1.0") is False


# --- interrogation de l'API ---

class Reponse:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}

    def json(self):
        return self._data


def release(tag="v1.2.0", assets=None, body="Notes"):
    return {'tag_name': tag, 'body': body,
            'assets': assets if assets is not None else [{
                'name': 'Lumina_Setup_1.2.0.exe',
                'browser_download_url': 'https://exemple/setup.exe',
                'size': 1000,
            }]}


def test_release_plus_recente_est_detectee():
    info = check_for_update("1.1.0", fetch=lambda url: Reponse(200, release()))

    assert info is not None
    assert info.version == "1.2.0"
    assert info.asset_name == "Lumina_Setup_1.2.0.exe"
    assert info.size == 1000


def test_meme_version_ne_propose_rien():
    info = check_for_update("1.2.0", fetch=lambda url: Reponse(200, release()))

    assert info is None


def test_aucune_release_publiee():
    """GitHub répond 404 tant qu'aucune release n'existe : silence."""
    assert check_for_update("1.1.0", fetch=lambda url: Reponse(404)) is None


def test_hors_ligne_ne_leve_jamais():
    def coupe(url):
        raise ConnectionError("hors ligne")

    assert check_for_update("1.1.0", fetch=coupe) is None


def test_release_sans_setup_est_ignoree():
    """Une release qui ne porte que l'exe portable n'est pas
    installable : l'exe portable ne sait pas migrer l'installation."""
    data = release(assets=[{'name': 'LuminaRecorder.exe',
                            'browser_download_url': 'https://x',
                            'size': 5}])

    assert check_for_update("1.1.0",
                            fetch=lambda url: Reponse(200, data)) is None


def test_le_setup_est_choisi_parmi_les_pieces_jointes():
    data = release(assets=[
        {'name': 'LuminaRecorder.exe',
         'browser_download_url': 'https://x/portable', 'size': 5},
        {'name': 'Lumina_Setup_1.2.0.exe',
         'browser_download_url': 'https://x/setup', 'size': 9},
    ])

    info = check_for_update("1.1.0", fetch=lambda url: Reponse(200, data))

    assert info.asset_url == 'https://x/setup'


def test_json_malforme_ne_leve_jamais():
    class Cassee:
        status_code = 200

        def json(self):
            raise ValueError("pas du JSON")

    assert check_for_update("1.1.0", fetch=lambda url: Cassee()) is None


# --- téléchargement ---

class FluxSimule:
    """Réponse en flux : sert `contenu` par blocs, peut mentir ou
    s'interrompre à mi-chemin."""

    def __init__(self, contenu=b"x" * 100, coupe_apres=None):
        self.contenu = contenu
        self.coupe_apres = coupe_apres

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        envoye = 0
        for i in range(0, len(self.contenu), 10):
            if self.coupe_apres is not None and envoye >= self.coupe_apres:
                raise ConnectionError("flux interrompu")
            bloc = self.contenu[i:i + 10]
            envoye += len(bloc)
            yield bloc


def info_pour(taille):
    return UpdateInfo(version="1.2.0", notes="", asset_url="https://x",
                      asset_name="Lumina_Setup_1.2.0.exe", size=taille)


def test_telechargement_complet_et_progression(tmp_path):
    progres = []

    chemin = download_setup(info_pour(100), str(tmp_path),
                            progress_cb=progres.append,
                            fetch_stream=lambda url: FluxSimule())

    assert chemin.endswith("Lumina_Setup_1.2.0.exe")
    assert (tmp_path / "Lumina_Setup_1.2.0.exe").read_bytes() == b"x" * 100
    assert progres[-1] == 1.0
    assert all(0 < p <= 1.0 for p in progres)


def test_taille_incorrecte_detruit_le_fichier(tmp_path):
    """Un installateur tronqué qui ressemble à un vrai .exe est pire
    qu'un échec : il s'exécuterait à moitié."""
    with pytest.raises(RuntimeError, match="incomplet"):
        download_setup(info_pour(999), str(tmp_path),
                       fetch_stream=lambda url: FluxSimule())

    assert list(tmp_path.iterdir()) == []


def test_flux_interrompu_ne_laisse_aucun_fichier(tmp_path):
    with pytest.raises(ConnectionError):
        download_setup(info_pour(100), str(tmp_path),
                       fetch_stream=lambda url: FluxSimule(coupe_apres=50))

    assert list(tmp_path.iterdir()) == []


# --- intégration avec le pont ---

def test_le_pont_refuse_la_mise_a_jour_pendant_l_enregistrement():
    from webui.bridge import LuminaBridge, RECORDING

    bridge = LuminaBridge()
    bridge.state = RECORDING
    bridge._update_info = info_pour(100)

    result = bridge.install_update()

    assert result['ok'] is False
    assert "enregistrement" in result['error'].lower()


def test_le_pont_refuse_sans_mise_a_jour_connue():
    from webui.bridge import LuminaBridge

    bridge = LuminaBridge()

    result = bridge.install_update()

    assert result['ok'] is False


def test_verification_manuelle_expose_la_release():
    from webui.bridge import LuminaBridge

    bridge = LuminaBridge()
    bridge._update_checker = lambda v: info_pour(1000)

    result = bridge.check_updates_now()

    assert result == {'ok': True, 'available': True, 'version': "1.2.0",
                      'notes': "", 'size': 1000}
    assert bridge._update_info is not None


def test_verification_manuelle_sans_release():
    from webui.bridge import LuminaBridge

    bridge = LuminaBridge()
    bridge._update_checker = lambda v: None

    result = bridge.check_updates_now()

    assert result['ok'] is True
    assert result['available'] is False
