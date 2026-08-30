import numpy as np
import cv2
import pytest

from core.recorder_core import RecorderCore
from filters.base import FrameFilter


class WhiteFilter(FrameFilter):
    name = "white"

    def process(self, frame):
        return np.full_like(frame, 255)


def make_frame(h=120, w=160):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_frames_written_to_disk_not_ram(tmp_path):
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)  # rediriger les fichiers temporaires
    for _ in range(20):
        rec._write_frame(make_frame())
    video_path, _ = rec.stop_recording()
    assert not hasattr(rec, 'frames') or rec.frames == []  # plus de buffer RAM
    cap = cv2.VideoCapture(video_path)
    assert cap.isOpened()
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 20
    cap.release()


def test_filters_applied_before_write(tmp_path):
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=False,
                       filters=[WhiteFilter()])
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    for _ in range(5):
        rec._write_frame(make_frame())
    video_path, _ = rec.stop_recording()
    cap = cv2.VideoCapture(video_path)
    ok, frame = cap.read()
    cap.release()
    assert ok
    assert frame.mean() > 200  # frames noires devenues blanches (MJPG avec perte)


def test_stop_without_frames_returns_empty(tmp_path):
    rec = RecorderCore(resolution="160x120", fps=10, audio_enabled=False)
    rec.is_recording = True
    rec._temp_dir = str(tmp_path)
    video_path, audio_path = rec.stop_recording()
    assert video_path == ""
    assert audio_path == ""
