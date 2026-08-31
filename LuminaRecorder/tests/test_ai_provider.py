"""Tests des tâches IA (titres, résumé, correction des sous-titres).

Aucun appel réseau : le moteur est remplacé par un faux qui renvoie des
réponses choisies, y compris malformées.
"""

import pytest

from services import ai_provider
from services.ai_provider import AITasks, build_engine, sends_data_offsite


class FauxMoteur:
    def __init__(self, reponse="", leve=False):
        self.reponse = reponse
        self.leve = leve
        self.appels = []

    def generate_text(self, prompt, system_prompt=None, **kwargs):
        self.appels.append({'prompt': prompt, 'system': system_prompt})
        if self.leve:
            raise RuntimeError("service injoignable")
        return self.reponse


# --- confidentialité ---

def test_ollama_ne_transmet_rien_hors_du_poste():
    assert sends_data_offsite('ollama') is False


@pytest.mark.parametrize("fournisseur",
                         ['openai', 'claude', 'gemini', 'deepseek', 'nvidia'])
def test_les_services_distants_sont_signales(fournisseur):
    assert sends_data_offsite(fournisseur) is True


def test_un_fournisseur_inconnu_est_suppose_distant():
    """Dans le doute, on avertit : ne jamais laisser croire qu'une
    donnée reste locale quand on n'en sait rien."""
    assert sends_data_offsite('service_inconnu') is True


# --- construction du moteur ---

def test_moteur_refuse_sans_cle(monkeypatch):
    """Une fonctionnalité sans moteur doit être visiblement
    indisponible, pas silencieusement inerte."""
    monkeypatch.setattr(ai_provider, 'has_api_key', lambda p: False)

    assert build_engine('openai') is None


def test_moteur_refuse_un_fournisseur_inconnu():
    assert build_engine('nimporte_quoi') is None


# --- titre de miniature ---

def test_titre_est_nettoye():
    moteur = FauxMoteur('Voici le titre : "Installer PyTorch en 5 minutes".')

    titre = AITasks(moteur).thumbnail_title("tutoriel")

    assert titre == "Installer PyTorch en 5 minutes"


def test_titre_limite_a_six_mots():
    moteur = FauxMoteur("un deux trois quatre cinq six sept huit")

    titre = AITasks(moteur).thumbnail_title("x")

    assert len(titre.split()) == 6


def test_titre_garde_la_premiere_ligne_utile():
    moteur = FauxMoteur("\n\nMon titre court\nEt une explication inutile")

    assert AITasks(moteur).thumbnail_title("x") == "Mon titre court"


def test_moteur_en_panne_ne_casse_pas_le_titre():
    """Une IA défaillante ne doit jamais faire perdre un enregistrement
    déjà capturé."""
    moteur = FauxMoteur(leve=True)

    assert AITasks(moteur).thumbnail_title("x") == ""


# --- résumé ---

def test_resume_est_transmis_tel_quel():
    moteur = FauxMoteur("- Point un\n- Point deux\nMots-clés : a, b, c")

    resume = AITasks(moteur).summary("transcription")

    assert "Point un" in resume
    assert "Mots-clés" in resume


def test_transcription_vide_n_appelle_pas_le_service():
    """Inutile d'envoyer une transcription vide à un service facturé."""
    moteur = FauxMoteur("ne devrait pas être appelé")

    assert AITasks(moteur).summary("   ") == ""
    assert moteur.appels == []


def test_transcription_longue_est_tronquee():
    moteur = FauxMoteur("résumé")

    AITasks(moteur).summary("mot " * 20000)

    envoye = moteur.appels[0]['prompt']
    assert len(envoye) < 14000
    assert "tronquée" in envoye


# --- correction des sous-titres ---

def test_correction_applique_les_lignes_renvoyees():
    moteur = FauxMoteur("1. Le module PyTorch gère\n2. Voici NumPy")

    corrige = AITasks(moteur).fix_subtitles(["le module pi torche gere",
                                             "voici numpaï"])

    assert corrige == ["Le module PyTorch gère", "Voici NumPy"]


def test_nombre_de_lignes_different_annule_la_correction():
    """Le texte est calé sur des horodatages : une ligne en moins
    désynchroniserait tout le fichier de sous-titres. Mieux vaut la
    transcription brute que des sous-titres décalés."""
    original = ["ligne une", "ligne deux", "ligne trois"]
    moteur = FauxMoteur("1. Ligne une\n2. Ligne deux")

    assert AITasks(moteur).fix_subtitles(original) == original


def test_lignes_fusionnees_annulent_la_correction():
    original = ["bonjour", "tout le monde"]
    moteur = FauxMoteur("1. Bonjour tout le monde")

    assert AITasks(moteur).fix_subtitles(original) == original


def test_reponse_non_numerotee_annule_la_correction():
    original = ["une", "deux"]
    moteur = FauxMoteur("Une\nDeux")

    assert AITasks(moteur).fix_subtitles(original) == original


def test_moteur_en_panne_rend_les_lignes_d_origine():
    original = ["une", "deux"]
    moteur = FauxMoteur(leve=True)

    assert AITasks(moteur).fix_subtitles(original) == original


def test_liste_vide_est_rendue_telle_quelle():
    moteur = FauxMoteur("ne devrait pas être appelé")

    assert AITasks(moteur).fix_subtitles([]) == []
    assert moteur.appels == []


def test_prefixe_ligne_ajoute_par_le_modele_est_retire():
    """Constaté en test réel avec qwen2.5 : malgré la numérotation déjà
    demandée, le modèle réécrit « 1. Ligne 1 : bonjour ». Sans nettoyage,
    « Ligne 1 : » serait incrusté dans les sous-titres."""
    moteur = FauxMoteur("1. Ligne 1 : bonjour tout le monde\n"
                        "2. Ligne 2 : on installe PyTorch")

    corrige = AITasks(moteur).fix_subtitles(["bonjour", "on installe"])

    assert corrige == ["bonjour tout le monde", "on installe PyTorch"]


def test_un_texte_commencant_par_ligne_n_est_pas_ampute():
    """« Ligne directrice : … » est du contenu, pas un préfixe."""
    moteur = FauxMoteur("1. Ligne directrice du projet")

    assert AITasks(moteur).fix_subtitles(["x"]) == ["Ligne directrice du projet"]


def test_la_consigne_interdit_de_reformuler():
    """La consigne est la seule protection contre un modèle qui
    réécrirait le propos de l'utilisateur."""
    moteur = FauxMoteur("1. a\n2. b")

    AITasks(moteur).fix_subtitles(["a", "b"])

    consigne = moteur.appels[0]['system'].lower()
    assert "ne reformule pas" in consigne
    assert "même nombre de lignes" in consigne


# --- les échecs doivent lever, jamais être renvoyés comme du texte ---

def test_ollama_absent_leve_au_lieu_de_renvoyer_du_texte(monkeypatch):
    """Une chaîne « Erreur Ollama: … » renvoyée comme réponse finirait
    incrustée dans une miniature ou écrite dans un fichier de résumé,
    présentée comme du contenu produit par le modèle."""
    import requests

    from services.ai_engine import LuminaAIEngine

    def refuse(*args, **kwargs):
        raise requests.exceptions.ConnectionError("injoignable")

    monkeypatch.setattr(requests, 'post', refuse)
    engine = LuminaAIEngine(provider='ollama')

    with pytest.raises(RuntimeError, match="ne répond pas"):
        engine.generate_text("test")


def test_modele_absent_est_explique(monkeypatch):
    """404 = modèle non installé. Le dire clairement plutôt que « erreur
    HTTP » : c'est le cas le plus fréquent et le plus simple à corriger."""
    import requests

    from services.ai_engine import LuminaAIEngine

    class Reponse404:
        status_code = 404

        def raise_for_status(self):
            error = requests.exceptions.HTTPError("404")
            error.response = self
            raise error

    monkeypatch.setattr(requests, 'post', lambda *a, **k: Reponse404())
    engine = LuminaAIEngine(provider='ollama', model='modele-fantome')

    with pytest.raises(RuntimeError, match="ollama pull modele-fantome"):
        engine.generate_text("test")


def test_une_panne_ne_devient_pas_un_titre_de_miniature(monkeypatch):
    """Bout en bout : le moteur lève, AITasks attrape, et le titre reste
    vide plutôt que de contenir un message d'erreur."""
    import requests

    from services.ai_engine import LuminaAIEngine

    def refuse(*args, **kwargs):
        raise requests.exceptions.ConnectionError("injoignable")

    monkeypatch.setattr(requests, 'post', refuse)
    engine = LuminaAIEngine(provider='ollama')

    titre = AITasks(engine).thumbnail_title("un tutoriel")

    assert titre == ""
