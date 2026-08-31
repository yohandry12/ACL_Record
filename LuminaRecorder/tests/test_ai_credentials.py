"""Tests du stockage des clés API.

Le coffre système est simulé : ces tests ne doivent jamais écrire dans le
gestionnaire d'identifiants réel de la machine qui les exécute.
"""

import pytest

from services import ai_credentials
from services.ai_credentials import (PROVIDERS, get_api_key, has_api_key,
                                     mask_key, provider_needs_key,
                                     providers_status, set_api_key)


class FauxCoffre:
    """Coffre en mémoire, à la place de keyring."""

    class errors:
        class PasswordDeleteError(Exception):
            pass

    def __init__(self):
        self.store = {}

    def get_keyring(self):
        return self

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def get_password(self, service, name):
        return self.store.get((service, name))

    def delete_password(self, service, name):
        if (service, name) not in self.store:
            raise self.errors.PasswordDeleteError()
        del self.store[(service, name)]


@pytest.fixture
def coffre(monkeypatch):
    faux = FauxCoffre()
    monkeypatch.setattr(ai_credentials, 'keyring', faux)
    monkeypatch.setattr(ai_credentials, 'credential_store_is_available',
                        lambda: True)
    # Aucune variable d'environnement ne doit fausser les tests
    for info in PROVIDERS.values():
        for name in info.get('env', []):
            monkeypatch.delenv(name, raising=False)
    for name in PROVIDERS:
        monkeypatch.delenv(f'LUMINA_{name.upper()}_API_KEY', raising=False)
    return faux


# --- écriture et lecture ---

def test_cle_enregistree_est_relue(coffre):
    assert set_api_key('openai', 'sk-test-123') is True

    assert get_api_key('openai') == 'sk-test-123'


def test_cle_vide_supprime_l_enregistrement(coffre):
    set_api_key('openai', 'sk-test-123')

    set_api_key('openai', '')

    assert get_api_key('openai') is None


def test_fournisseur_inconnu_est_refuse(coffre):
    assert set_api_key('fournisseur_invente', 'x') is False
    assert get_api_key('fournisseur_invente') is None


def test_sans_coffre_rien_n_est_ecrit(monkeypatch):
    """Sans coffre système, on refuse plutôt que d'écrire ailleurs :
    une clé ne doit jamais atterrir en clair par un chemin de secours."""
    monkeypatch.setattr(ai_credentials, 'credential_store_is_available',
                        lambda: False)

    assert set_api_key('openai', 'sk-test') is False


# --- variables d'environnement ---

def test_variable_lumina_sert_de_secours(coffre, monkeypatch):
    monkeypatch.setenv('LUMINA_OPENAI_API_KEY', 'sk-env')

    assert get_api_key('openai') == 'sk-env'


def test_variable_standard_sert_de_secours(coffre, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-env')

    assert get_api_key('claude') == 'sk-ant-env'


def test_le_coffre_prime_sur_l_environnement(coffre, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-env')
    set_api_key('openai', 'sk-coffre')

    assert get_api_key('openai') == 'sk-coffre'


# --- Ollama : local, sans clé ---

def test_ollama_ne_demande_pas_de_cle():
    assert provider_needs_key('ollama') is False


def test_ollama_est_utilisable_sans_cle(coffre):
    assert has_api_key('ollama') is True


def test_ollama_est_marque_local():
    assert PROVIDERS['ollama']['local'] is True
    assert all(not info['local'] for name, info in PROVIDERS.items()
               if name != 'ollama')


def test_les_six_fournisseurs_demandes_sont_presents():
    assert set(PROVIDERS) == {'ollama', 'openai', 'claude', 'gemini',
                              'deepseek', 'nvidia'}


# --- masquage ---

def test_la_cle_masquee_ne_revele_pas_le_secret():
    masquee = mask_key('sk-proj-abcdefghijklmnop')

    assert 'abcdefghijkl' not in masquee
    assert masquee.startswith('sk-proj')
    assert masquee.endswith('mnop')


def test_cle_courte_reste_masquee():
    masquee = mask_key('court123')

    assert 'court' not in masquee


def test_cle_absente_donne_une_chaine_vide():
    assert mask_key(None) == ""
    assert mask_key("") == ""


# --- état pour l'interface ---

def test_l_etat_ne_contient_aucune_cle_en_clair(coffre):
    """L'interface reçoit cet objet : une clé en clair y serait exposée
    dans la page, donc lisible par n'importe quel script chargé."""
    set_api_key('openai', 'sk-secret-a-ne-pas-divulguer')

    status = providers_status()

    texte = repr(status)
    assert 'sk-secret-a-ne-pas-divulguer' not in texte
    openai = next(p for p in status if p['id'] == 'openai')
    assert openai['has_key'] is True
    assert 'secret-a-ne-pas' not in openai['masked_key']


def test_l_etat_signale_ce_qui_sort_du_poste(coffre):
    """L'utilisateur doit pouvoir distinguer local et distant avant
    d'envoyer le contenu de ses enregistrements."""
    status = providers_status()

    ollama = next(p for p in status if p['id'] == 'ollama')
    openai = next(p for p in status if p['id'] == 'openai')
    assert ollama['local'] is True
    assert 'Aucune donnée ne sort' in ollama['note']
    assert openai['local'] is False
    assert 'serveurs' in openai['note']
