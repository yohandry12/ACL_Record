"""Tests des post-processeurs IA (résumé, correction des sous-titres)."""

import pytest

from postprocess.ai_text_processors import (SubtitleFixProcessor,
                                            SummaryProcessor, build_srt,
                                            parse_srt)


SRT = """1
00:00:00,000 --> 00:00:02,500
le module pi torche gere les tenseurs

2
00:00:02,500 --> 00:00:05,000
on utilise pipe install torch

3
00:00:05,000 --> 00:00:07,000
et numpaï pour les tableaux
"""


class FauxMoteur:
    """Moteur IA factice : renvoie les réponses qu'on lui donne."""

    def __init__(self, reponses=None, leve=False):
        self.reponses = list(reponses or [])
        self.leve = leve
        self.appels = []

    def generate_text(self, prompt, system_prompt=None, **kwargs):
        self.appels.append(prompt)
        if self.leve:
            raise RuntimeError("service injoignable")
        return self.reponses.pop(0) if self.reponses else ""


@pytest.fixture
def video(tmp_path):
    """Une vidéo factice accompagnée de son .srt."""
    chemin = tmp_path / "capture.mp4"
    chemin.write_bytes(b"video")
    (tmp_path / "capture.srt").write_text(SRT, encoding='utf-8')
    return str(chemin)


def rien(_):
    pass


# --- analyse du .srt ---

def test_le_srt_est_decoupe_en_blocs():
    blocs = parse_srt(SRT)

    assert len(blocs) == 3
    assert blocs[0][1] == "00:00:00,000 --> 00:00:02,500"
    assert blocs[2][2] == "et numpaï pour les tableaux"


def test_bloc_multiligne_est_joint():
    contenu = "1\n00:00:00,000 --> 00:00:02,000\npremiere ligne\nseconde ligne\n"

    blocs = parse_srt(contenu)

    assert blocs[0][2] == "premiere ligne seconde ligne"


def test_reconstruction_conserve_les_horodatages():
    blocs = parse_srt(SRT)

    assert parse_srt(build_srt(blocs)) == blocs


# --- résumé ---

def test_resume_ecrit_un_fichier(video):
    moteur = FauxMoteur(["- Un point\nMots-clés : a, b"])

    r = SummaryProcessor(moteur).run(video, None, rien)

    assert r.success is True
    assert r.output_path.endswith("_resume.md")
    with open(r.output_path, encoding='utf-8') as f:
        assert "Un point" in f.read()


def test_resume_exige_les_sous_titres(tmp_path):
    """Ne pas transcrire une seconde fois : le dire clairement."""
    seule = tmp_path / "seule.mp4"
    seule.write_bytes(b"video")

    r = SummaryProcessor(FauxMoteur()).run(str(seule), None, rien)

    assert r.success is False
    assert "sous-titres" in r.error.lower()


def test_resume_sans_moteur_echoue_explicitement(video):
    """Aucune fonctionnalité IA ne doit sembler active sans moteur."""
    r = SummaryProcessor(None).run(video, None, rien)

    assert r.success is False
    assert "fournisseur" in r.error.lower()


def test_moteur_muet_ne_produit_pas_de_fichier_vide(video):
    r = SummaryProcessor(FauxMoteur([""])).run(video, None, rien)

    assert r.success is False


# --- correction des sous-titres ---

def test_correction_ecrit_un_srt_corrige(video):
    moteur = FauxMoteur(["1. Le module PyTorch gère les tenseurs\n"
                         "2. On utilise pip install torch\n"
                         "3. Et NumPy pour les tableaux"])

    r = SubtitleFixProcessor(moteur).run(video, None, rien)

    assert r.success is True
    assert r.output_path.endswith("_corrige.srt")
    with open(r.output_path, encoding='utf-8') as f:
        assert "PyTorch" in f.read()


def test_les_horodatages_sont_intacts_apres_correction(video):
    """Le point le plus important : une correction qui décalerait les
    horodatages rendrait les sous-titres inutilisables."""
    moteur = FauxMoteur(["1. Texte un\n2. Texte deux\n3. Texte trois"])

    r = SubtitleFixProcessor(moteur).run(video, None, rien)

    with open(r.output_path, encoding='utf-8') as f:
        corriges = parse_srt(f.read())
    originaux = parse_srt(SRT)
    assert [b[1] for b in corriges] == [b[1] for b in originaux]
    assert [b[0] for b in corriges] == [b[0] for b in originaux]


def test_le_srt_d_origine_n_est_jamais_modifie(video):
    """La transcription brute reste disponible si la correction déçoit."""
    from pathlib import Path
    avant = Path(video).with_suffix('.srt').read_text(encoding='utf-8')
    moteur = FauxMoteur(["1. A\n2. B\n3. C"])

    SubtitleFixProcessor(moteur).run(video, None, rien)

    assert Path(video).with_suffix('.srt').read_text(encoding='utf-8') == avant


def test_reponse_incoherente_laisse_le_texte_intact(video):
    """Le modèle renvoie deux lignes pour trois : on garde l'original
    plutôt que de désynchroniser."""
    moteur = FauxMoteur(["1. Une seule\n2. Deux"])

    r = SubtitleFixProcessor(moteur).run(video, None, rien)

    assert r.success is True
    assert "Aucune correction" in (r.error or "")


def test_moteur_en_panne_laisse_le_texte_intact(video):
    r = SubtitleFixProcessor(FauxMoteur(leve=True)).run(video, None, rien)

    assert r.success is True
    assert "Aucune correction" in (r.error or "")


def test_correction_sans_moteur_echoue_explicitement(video):
    r = SubtitleFixProcessor(None).run(video, None, rien)

    assert r.success is False


def test_correction_exige_les_sous_titres(tmp_path):
    seule = tmp_path / "seule.mp4"
    seule.write_bytes(b"video")

    r = SubtitleFixProcessor(FauxMoteur()).run(str(seule), None, rien)

    assert r.success is False
    assert "sous-titres" in r.error.lower()


def test_les_longues_transcriptions_sont_decoupees(tmp_path):
    """Envoyer 400 lignes d'un coup dépasse la fenêtre des petits
    modèles, qui renvoient alors un nombre de lignes incorrect."""
    chemin = tmp_path / "longue.mp4"
    chemin.write_bytes(b"video")
    blocs = [f"{i}\n00:00:{i:02d},000 --> 00:00:{i + 1:02d},000\nligne {i}"
             for i in range(1, 101)]
    (tmp_path / "longue.srt").write_text("\n\n".join(blocs) + "\n",
                                         encoding='utf-8')
    moteur = FauxMoteur([])

    SubtitleFixProcessor(moteur).run(str(chemin), None, rien)

    # 100 lignes par lots de 40 : trois appels
    assert len(moteur.appels) == 3
