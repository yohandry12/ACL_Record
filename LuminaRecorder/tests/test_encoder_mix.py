"""Tests du mixage micro + son système.

Vérifient la commande FFmpeg construite, sans lancer d'encodage : ce
qui compte ici est la présence des options qui décident du niveau
sonore final.
"""

from core.encoder import VideoEncoder


def commande_de_mixage(monkeypatch, tmp_path, gain=1.0):
    """Récupère la commande FFmpeg construite pour micro + son système."""
    capturee = {}

    def faux_run(cmd, *args, **kwargs):
        capturee['cmd'] = cmd

        class Resultat:
            returncode = 0
            stderr = ''
            stdout = ''
        return Resultat()

    import core.encoder as encoder_module
    monkeypatch.setattr(encoder_module.subprocess, 'run', faux_run)

    video = tmp_path / "v.avi"
    audio = tmp_path / "mic.wav"
    systeme = tmp_path / "sys.wav"
    for f in (video, audio, systeme):
        f.write_bytes(b"fake")

    encoder = VideoEncoder()
    encoder.encode(video_path=str(video), audio_path=str(audio),
                   output_path=str(tmp_path / "out.mp4"),
                   resolution="1280x720", fps=30, bitrate="2500k",
                   audio_gain=gain, system_audio_path=str(systeme))
    return ' '.join(capturee.get('cmd', []))


def test_le_micro_n_est_pas_divise_par_deux(monkeypatch, tmp_path):
    """Constaté en usage réel : la voix était inaudible sous la
    bande-son d'une vidéo. amix divise CHAQUE entrée par le nombre
    d'entrées, donc le micro sortait à -6 dB. normalize=0 l'empêche."""
    cmd = commande_de_mixage(monkeypatch, tmp_path)

    assert 'amix' in cmd
    assert 'normalize=0' in cmd


def test_le_son_systeme_passe_en_arriere_plan(monkeypatch, tmp_path):
    """La voix est le propos de l'enregistrement : le son système est
    atténué pour ne pas la couvrir."""
    cmd = commande_de_mixage(monkeypatch, tmp_path, gain=1.0)

    assert 'volume=1.0[mic]' in cmd
    assert 'volume=0.65[sys]' in cmd


def test_le_gain_utilisateur_s_applique_aux_deux_sources(monkeypatch,
                                                         tmp_path):
    cmd = commande_de_mixage(monkeypatch, tmp_path, gain=2.0)

    assert 'volume=2.0[mic]' in cmd
    assert 'volume=1.3[sys]' in cmd     # 2.0 x 0.65


def test_pas_de_remontee_de_gain_dans_les_silences(monkeypatch, tmp_path):
    """Sans dropout_transition=0, amix remonte le niveau des sources
    restantes quand une se tait : le son système enflerait à chaque
    pause de la voix."""
    cmd = commande_de_mixage(monkeypatch, tmp_path)

    assert 'dropout_transition=0' in cmd
