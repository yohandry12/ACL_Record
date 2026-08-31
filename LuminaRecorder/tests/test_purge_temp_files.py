"""C3 : purge des .keep.wav orphelins au démarrage (temp/ preservé après
une interruption du post-traitement)."""
import os

from ui.main_window import MainWindow


def test_purge_removes_orphan_keep_wav_files(tmp_path, monkeypatch):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    orphan = temp_dir / "lumina_audio_20260101_000000.wav.keep.wav"
    orphan.write_bytes(b"fake wav data")
    other = temp_dir / "lumina_audio_20260101_000000.wav"
    other.write_bytes(b"keep me")

    monkeypatch.chdir(tmp_path)

    # _purge_temp_files ne touche pas tkinter : appelée directement sur
    # une instance non initialisée pour éviter de construire toute la UI.
    MainWindow._purge_temp_files(object.__new__(MainWindow))

    assert not orphan.exists()
    assert other.exists()  # seuls les .keep.wav sont purgés


def test_purge_ignores_missing_temp_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # pas de dossier temp/ ici
    # Ne doit lever aucune exception
    MainWindow._purge_temp_files(object.__new__(MainWindow))
