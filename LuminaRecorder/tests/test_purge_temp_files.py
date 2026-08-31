"""C3 : purge des .keep.wav orphelins au démarrage (copies préservées
après une interruption du post-traitement)."""

from ui import main_window
from ui.main_window import MainWindow


def test_purge_removes_orphan_keep_wav_files(tmp_path, monkeypatch):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    orphan = temp_dir / "lumina_audio_20260101_000000.wav.keep.wav"
    orphan.write_bytes(b"fake wav data")
    other = temp_dir / "lumina_audio_20260101_000000.wav"
    other.write_bytes(b"keep me")

    # get_temp_dir() est ancré sur LOCALAPPDATA : on le redirige plutôt
    # que de compter sur le dossier courant
    monkeypatch.setattr(main_window, 'get_temp_dir', lambda: temp_dir)

    # _purge_temp_files ne touche pas tkinter : appelée directement sur
    # une instance non initialisée pour éviter de construire toute la UI.
    MainWindow._purge_temp_files(object.__new__(MainWindow))

    assert not orphan.exists()
    assert other.exists()  # seuls les .keep.wav sont purgés


def test_purge_ignores_missing_temp_dir(tmp_path, monkeypatch):
    absent = tmp_path / "inexistant"
    monkeypatch.setattr(main_window, 'get_temp_dir', lambda: absent)
    # Ne doit lever aucune exception
    MainWindow._purge_temp_files(object.__new__(MainWindow))
