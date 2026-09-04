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
    """Mesuré sur un enregistrement réel : la bande vocale sortait
    2,3 dB SOUS le reste, la voix était couverte. Elle est remontée et
    le son système reculé — mesuré sur signaux de test : le rapport
    voix/fond passe de -16,1 dB à +9,9 dB."""
    cmd = commande_de_mixage(monkeypatch, tmp_path, gain=1.0)

    assert 'volume=1.5,' in cmd          # voix remontée
    assert 'volume=0.35[sys]' in cmd     # système reculé


def test_la_voix_est_egalisee(monkeypatch, tmp_path):
    """Une phrase prononcée en s'éloignant du micro doit rester
    audible : dynaudnorm égalise sans écraser la dynamique."""
    cmd = commande_de_mixage(monkeypatch, tmp_path)

    assert 'dynaudnorm' in cmd


def test_la_somme_ne_sature_pas(monkeypatch, tmp_path):
    """Sans normalisation d'amix, la somme des deux sources peut
    dépasser 0 dBFS : un limiteur protège la sortie."""
    cmd = commande_de_mixage(monkeypatch, tmp_path)

    assert 'alimiter' in cmd


def test_le_gain_utilisateur_s_applique_aux_deux_sources(monkeypatch,
                                                         tmp_path):
    cmd = commande_de_mixage(monkeypatch, tmp_path, gain=2.0)

    assert 'volume=3.0,' in cmd          # 2.0 x 1.5
    assert 'volume=0.7[sys]' in cmd      # 2.0 x 0.35


def commande_video_seule(monkeypatch, tmp_path, nom_video):
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
    video = tmp_path / nom_video
    video.write_bytes(b"fake")
    VideoEncoder().encode(video_path=str(video), audio_path=None,
                          output_path=str(tmp_path / "out.mp4"),
                          resolution="1280x720", fps=30)
    return capturee.get('cmd', [])


def test_un_flux_mjpeg_brut_est_lu_a_la_cadence_nominale(monkeypatch,
                                                         tmp_path):
    """Le flux brut est un MJPEG nu à cadence constante : FFmpeg doit
    savoir qu'il s'agit de ce format et à quelle cadence le lire. Sans
    -f mjpeg, un fichier sans en-tête n'est pas reconnu ; sans
    -framerate, il serait lu à 25 im/s et la vidéo dériverait."""
    cmd = commande_video_seule(monkeypatch, tmp_path, "v.mjpeg")
    i = cmd.index('-i')

    assert cmd[i - 4:i] == ['-f', 'mjpeg', '-framerate', '30']
    assert '-r' not in cmd[:i]


def test_un_avi_garde_la_lecture_historique(monkeypatch, tmp_path):
    cmd = commande_video_seule(monkeypatch, tmp_path, "v.avi")
    i = cmd.index('-i')

    assert cmd[i - 2:i] == ['-r', '30']


def test_pas_de_remontee_de_gain_dans_les_silences(monkeypatch, tmp_path):
    """Sans dropout_transition=0, amix remonte le niveau des sources
    restantes quand une se tait : le son système enflerait à chaque
    pause de la voix."""
    cmd = commande_de_mixage(monkeypatch, tmp_path)

    assert 'dropout_transition=0' in cmd
