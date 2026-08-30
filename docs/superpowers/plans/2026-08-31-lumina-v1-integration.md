# Lumina v1 — Intégration des modules IA : Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer une v1 fiable de LuminaRecorder : capture sans limite de RAM, filtres temps réel (blur, clean canvas, overlay) avec garde-fou performance, post-traitement (sous-titres Whisper, coupes Magic Cut via FFmpeg), carte UI « Options IA » persistée en config.

**Architecture:** Chaîne de filtres frame-par-frame appliquée pendant la capture (écriture disque en continu), puis post-processeurs séquentiels après l'arrêt, exécutés dans un thread avec fenêtre de progression. Les moteurs existants (`src/ai/`, `src/services/`) ne sont pas modifiés : les nouveaux modules `src/filters/` et `src/postprocess/` les enveloppent.

**Tech Stack:** Python 3.8+, tkinter, mss, opencv-python (cv2), numpy, pyaudio, FFmpeg (exécutable externe), faster-whisper (optionnel), pytest.

## Global Constraints

- Tout le travail se fait dans `LuminaRecorder/` — le prototype racine (`screen_recorder.py`, `src/` racine) n'est jamais touché.
- Règle d'or : **on ne perd jamais un enregistrement**. Aucune exception d'un filtre ou d'un post-processeur ne doit interrompre la capture ni supprimer le .mp4 original.
- Les moteurs existants `src/ai/*` et `src/services/*` ne sont pas modifiés (leurs blocs `__main__` doivent continuer de fonctionner).
- Les post-processeurs produisent des fichiers séparés à côté de l'original (`X.srt`, `X_cut.mp4`) — jamais d'écrasement.
- Ordre des post-processeurs fixe : sous-titres AVANT Magic Cut.
- Toutes les cases « Options IA » sont décochées par défaut.
- Imports internes au style du projet : `main.py` insère `src/` dans `sys.path`, donc les imports s'écrivent `from filters.base import ...` (pas `from src.filters...`).
- Tests : pytest, dossier `LuminaRecorder/tests/`. Les tests dépendant de FFmpeg utilisent `pytest.mark.skipif(shutil.which("ffmpeg") is None, ...)`.
- Commits : messages en français, préfixe conventionnel (`feat:`, `fix:`, `test:`).
- Toutes les commandes s'exécutent depuis `LuminaRecorder/` (`cd LuminaRecorder` d'abord).

---

### Task 1 : Interface FrameFilter + FilterChain avec garde-fou performance

**Files:**
- Create: `LuminaRecorder/src/filters/__init__.py`
- Create: `LuminaRecorder/src/filters/base.py`
- Create: `LuminaRecorder/tests/__init__.py` (vide)
- Create: `LuminaRecorder/tests/conftest.py`
- Test: `LuminaRecorder/tests/test_filter_chain.py`

**Interfaces:**
- Consumes: rien (fondation).
- Produces:
  - `FrameFilter` (ABC) : attribut `name: str`, attribut `enabled: bool` (True à l'init), méthode abstraite `process(self, frame: np.ndarray) -> np.ndarray`.
  - `FilterChain(filters: List[FrameFilter], frame_budget: float, on_disable: Optional[Callable[[str], None]] = None, max_slow_frames: int = 30)` : méthode `process(self, frame: np.ndarray) -> np.ndarray` qui applique chaque filtre actif en série ; désactive un filtre (`enabled = False` + appel `on_disable(name)`) s'il dépasse `frame_budget` secondes sur `max_slow_frames` frames consécutives, ou immédiatement s'il lève une exception ; propriété `active_count: int`.

- [ ] **Step 1 : Installer pytest et créer l'infra de test**

```powershell
cd LuminaRecorder
pip install pytest
New-Item -ItemType Directory -Force tests
New-Item -ItemType File tests\__init__.py
```

Créer `tests/conftest.py` :

```python
"""Configuration pytest : rend src/ importable comme le fait main.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
```

- [ ] **Step 2 : Écrire les tests qui échouent**

`tests/test_filter_chain.py` :

```python
import time
import numpy as np
import pytest

from filters.base import FrameFilter, FilterChain


class IdentityFilter(FrameFilter):
    name = "identity"

    def process(self, frame):
        return frame


class InvertFilter(FrameFilter):
    name = "invert"

    def process(self, frame):
        return 255 - frame


class SlowFilter(FrameFilter):
    name = "slow"

    def __init__(self, delay=0.02):
        super().__init__()
        self.delay = delay

    def process(self, frame):
        time.sleep(self.delay)
        return frame


class CrashFilter(FrameFilter):
    name = "crash"

    def process(self, frame):
        raise RuntimeError("boom")


def make_frame():
    return np.zeros((10, 10, 3), dtype=np.uint8)


def test_chain_applies_filters_in_order():
    chain = FilterChain([InvertFilter()], frame_budget=1.0)
    out = chain.process(make_frame())
    assert out.max() == 255  # frame noire inversée -> blanche


def test_disabled_filter_is_skipped():
    f = InvertFilter()
    f.enabled = False
    chain = FilterChain([f], frame_budget=1.0)
    out = chain.process(make_frame())
    assert out.max() == 0  # rien appliqué


def test_slow_filter_disabled_after_30_consecutive_slow_frames():
    disabled = []
    f = SlowFilter(delay=0.02)
    chain = FilterChain([f], frame_budget=0.001,
                        on_disable=disabled.append, max_slow_frames=30)
    frame = make_frame()
    for _ in range(30):
        chain.process(frame)
    assert f.enabled is False
    assert disabled == ["slow"]
    assert chain.active_count == 0


def test_fast_frame_resets_slow_counter():
    f = SlowFilter(delay=0.02)
    chain = FilterChain([f], frame_budget=0.001, max_slow_frames=30)
    frame = make_frame()
    for _ in range(29):
        chain.process(frame)
    f.delay = 0.0  # devient rapide : le compteur doit se réinitialiser
    chain.process(frame)
    f.delay = 0.02
    for _ in range(29):
        chain.process(frame)
    assert f.enabled is True  # jamais 30 lentes consécutives


def test_crashing_filter_disabled_immediately_frame_preserved():
    disabled = []
    chain = FilterChain([CrashFilter(), InvertFilter()],
                        frame_budget=1.0, on_disable=disabled.append)
    out = chain.process(make_frame())
    assert disabled == ["crash"]
    assert out.max() == 255  # le filtre suivant a quand même tourné
```

- [ ] **Step 3 : Vérifier l'échec**

Run : `python -m pytest tests/test_filter_chain.py -v`
Attendu : ERROR/FAIL — `ModuleNotFoundError: No module named 'filters'`.

- [ ] **Step 4 : Implémenter**

`src/filters/base.py` :

```python
"""
Lumina Filters - Chaîne de filtres temps réel appliqués frame par frame.

Un FrameFilter transforme une frame BGR (numpy) pendant la capture.
FilterChain applique les filtres actifs en série avec un garde-fou :
un filtre trop lent (budget dépassé sur N frames consécutives) ou qui
lève une exception est désactivé à chaud — l'enregistrement continue.
"""

import time
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

import numpy as np


class FrameFilter(ABC):
    """Filtre appliqué à chaque frame pendant l'enregistrement."""

    name: str = "filter"

    def __init__(self):
        self.enabled = True

    @abstractmethod
    def process(self, frame: np.ndarray) -> np.ndarray:
        """Retourne la frame transformée (mêmes dimensions)."""
        ...


class FilterChain:
    """Applique une liste de FrameFilter avec garde-fou performance."""

    def __init__(self, filters: List[FrameFilter], frame_budget: float,
                 on_disable: Optional[Callable[[str], None]] = None,
                 max_slow_frames: int = 30):
        self.filters = filters
        self.frame_budget = frame_budget
        self.on_disable = on_disable
        self.max_slow_frames = max_slow_frames
        self._slow_counts = {id(f): 0 for f in filters}

    @property
    def active_count(self) -> int:
        return sum(1 for f in self.filters if f.enabled)

    def _disable(self, flt: FrameFilter):
        flt.enabled = False
        if self.on_disable:
            self.on_disable(flt.name)

    def process(self, frame: np.ndarray) -> np.ndarray:
        for flt in self.filters:
            if not flt.enabled:
                continue
            start = time.perf_counter()
            try:
                frame = flt.process(frame)
            except Exception:
                self._disable(flt)
                continue
            elapsed = time.perf_counter() - start
            if elapsed > self.frame_budget:
                self._slow_counts[id(flt)] += 1
                if self._slow_counts[id(flt)] >= self.max_slow_frames:
                    self._disable(flt)
            else:
                self._slow_counts[id(flt)] = 0
        return frame
```

`src/filters/__init__.py` :

```python
"""Lumina Filters - Filtres temps réel pour l'enregistrement."""

from .base import FrameFilter, FilterChain

__all__ = ['FrameFilter', 'FilterChain']
```

- [ ] **Step 5 : Vérifier le succès**

Run : `python -m pytest tests/test_filter_chain.py -v`
Attendu : 5 PASS.

- [ ] **Step 6 : Commit**

```powershell
git add tests src/filters
git commit -m "feat: chaine de filtres temps reel avec garde-fou performance"
```

---

### Task 2 : Les trois filtres concrets (Blur, Clean Canvas, Overlay)

**Files:**
- Create: `LuminaRecorder/src/filters/privacy_blur_filter.py`
- Create: `LuminaRecorder/src/filters/clean_canvas_filter.py`
- Create: `LuminaRecorder/src/filters/overlay_filter.py`
- Modify: `LuminaRecorder/src/filters/__init__.py`
- Test: `LuminaRecorder/tests/test_concrete_filters.py`

**Interfaces:**
- Consumes: `FrameFilter` (Task 1) ; moteurs existants `services.privacy_blur.PrivacyBlurService`, `ai.clean_canvas.CleanCanvasEngine`, `services.system_overlay.SystemOverlayService` (non modifiés).
- Produces:
  - `PrivacyBlurFilter()` — `name = "privacy_blur"`, expose `self.service` (le `PrivacyBlurService` interne, pour ajouter des zones).
  - `CleanCanvasFilter()` — `name = "clean_canvas"`.
  - `OverlayFilter()` — `name = "overlay"`.

- [ ] **Step 1 : Écrire les tests qui échouent**

`tests/test_concrete_filters.py` :

```python
import numpy as np

from filters.privacy_blur_filter import PrivacyBlurFilter
from filters.clean_canvas_filter import CleanCanvasFilter
from filters.overlay_filter import OverlayFilter


def make_frame(h=200, w=300):
    # Bruit aléatoire : un flou gaussien y est mesurable (variance chute)
    rng = np.random.default_rng(42)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


def test_privacy_blur_blurs_registered_region():
    flt = PrivacyBlurFilter()
    flt.service.add_blur_region(50, 50, 100, 60, blur_type='gaussian',
                                strength=25, reason='test')
    frame = make_frame()
    out = flt.process(frame)
    region_before = frame[50:110, 50:150].astype(float)
    region_after = out[50:110, 50:150].astype(float)
    assert out.shape == frame.shape
    assert region_after.var() < region_before.var()  # flou = variance réduite


def test_privacy_blur_without_region_is_identity():
    flt = PrivacyBlurFilter()
    frame = make_frame()
    out = flt.process(frame)
    assert np.array_equal(out, frame)


def test_clean_canvas_returns_same_shape():
    flt = CleanCanvasFilter()
    frame = make_frame()
    out = flt.process(frame)
    assert out.shape == frame.shape
    assert out.dtype == frame.dtype


def test_overlay_draws_pixels():
    flt = OverlayFilter()
    frame = np.zeros((400, 600, 3), dtype=np.uint8)
    flt.process(frame)          # 1er appel : initialise les métriques
    out = flt.process(frame)
    assert out.shape == frame.shape
    assert out.sum() > 0        # du texte/fond a été dessiné sur du noir
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `python -m pytest tests/test_concrete_filters.py -v`
Attendu : FAIL — modules inexistants.

- [ ] **Step 3 : Implémenter les trois wrappers**

`src/filters/privacy_blur_filter.py` :

```python
"""Adaptateur FrameFilter pour PrivacyBlurService (flou confidentialité)."""

import numpy as np

from services.privacy_blur import PrivacyBlurService
from .base import FrameFilter


class PrivacyBlurFilter(FrameFilter):
    name = "privacy_blur"

    def __init__(self):
        super().__init__()
        self.service = PrivacyBlurService()

    def process(self, frame: np.ndarray) -> np.ndarray:
        return self.service.process_frame(frame)
```

`src/filters/clean_canvas_filter.py` :

```python
"""Adaptateur FrameFilter pour CleanCanvasEngine (masquage notifications)."""

import numpy as np

from ai.clean_canvas import CleanCanvasEngine
from .base import FrameFilter


class CleanCanvasFilter(FrameFilter):
    name = "clean_canvas"

    def __init__(self):
        super().__init__()
        self.engine = CleanCanvasEngine(auto_hide=True)

    def process(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        return self.engine.process_frame(frame, w, h)
```

`src/filters/overlay_filter.py` :

```python
"""Adaptateur FrameFilter pour SystemOverlayService (métriques CPU/RAM/FPS)."""

import numpy as np

from services.system_overlay import SystemOverlayService, OverlayConfig
from .base import FrameFilter


class OverlayFilter(FrameFilter):
    name = "overlay"

    def __init__(self):
        super().__init__()
        # update_interval bas pour que les métriques apparaissent vite
        self.service = SystemOverlayService(OverlayConfig(update_interval=0.5))

    def process(self, frame: np.ndarray) -> np.ndarray:
        return self.service.draw_overlay(frame)
```

Mettre à jour `src/filters/__init__.py` :

```python
"""Lumina Filters - Filtres temps réel pour l'enregistrement."""

from .base import FrameFilter, FilterChain
from .privacy_blur_filter import PrivacyBlurFilter
from .clean_canvas_filter import CleanCanvasFilter
from .overlay_filter import OverlayFilter

__all__ = ['FrameFilter', 'FilterChain', 'PrivacyBlurFilter',
           'CleanCanvasFilter', 'OverlayFilter']
```

- [ ] **Step 4 : Vérifier le succès**

Run : `python -m pytest tests/test_concrete_filters.py -v`
Attendu : 4 PASS. (Le test overlay tolère `update_metrics` : la 2e frame contient au moins le fond semi-transparent. Si `psutil.cpu_percent(interval=0.1)` ralentit le test, c'est acceptable — c'est un test, pas la boucle de capture.)

- [ ] **Step 5 : Commit**

```powershell
git add src/filters tests/test_concrete_filters.py
git commit -m "feat: filtres blur, clean canvas et overlay (adaptateurs)"
```

---

### Task 3 : RecorderCore — écriture disque en continu + chaîne de filtres

**Files:**
- Modify: `LuminaRecorder/src/core/recorder_core.py` (remplacement des méthodes de capture ; `_save_raw_frames` supprimée)
- Test: `LuminaRecorder/tests/test_recorder_core.py`

**Interfaces:**
- Consumes: `FilterChain`, `FrameFilter` (Task 1).
- Produces (signatures utilisées par la UI en Task 6/7) :
  - `RecorderCore(resolution="1920x1080", fps=30, audio_enabled=True, audio_gain=0.5, filters=None, on_filter_disabled=None)` — `filters: Optional[List[FrameFilter]]`, `on_filter_disabled: Optional[Callable[[str], None]]`.
  - `start_recording(output_path: str) -> bool` (inchangé).
  - `stop_recording() -> Optional[Tuple[str, str]]` — `(chemin_video_avi, chemin_audio_wav_ou_"")`, comme aujourd'hui mais annotation corrigée.
  - Méthode interne testable `_write_frame(frame: np.ndarray) -> None` : applique la chaîne puis écrit dans le writer (ouvre le writer à la première frame).

- [ ] **Step 1 : Écrire les tests qui échouent**

`tests/test_recorder_core.py` :

```python
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
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `python -m pytest tests/test_recorder_core.py -v`
Attendu : FAIL — `_write_frame` inexistante, `filters` inconnu du constructeur.

- [ ] **Step 3 : Implémenter le refactor**

Dans `src/core/recorder_core.py` :

Remplacer les imports du haut pour ajouter :

```python
from filters.base import FilterChain, FrameFilter
from typing import Optional, Tuple, Dict, List, Callable
```

Remplacer `__init__` (nouveaux paramètres et état ; le buffer `self.frames` disparaît) :

```python
    def __init__(self, resolution: str = "1920x1080", fps: int = 30,
                 audio_enabled: bool = True, audio_gain: float = 0.5,
                 filters: Optional[List[FrameFilter]] = None,
                 on_filter_disabled: Optional[Callable[[str], None]] = None):
        self.resolution = resolution
        self.fps = fps
        self.audio_enabled = audio_enabled
        self.audio_gain = audio_gain

        self.filter_chain = FilterChain(
            filters or [],
            frame_budget=1.0 / fps,
            on_disable=on_filter_disabled
        )

        self.is_recording = False
        self.recording_thread = None
        self.audio_thread = None

        self.audio_frames = []
        self._writer = None            # cv2.VideoWriter, ouvert à la 1re frame
        self._raw_video_path = ""
        self._frame_count = 0
        self._temp_dir = str(Path(os.getcwd()) / "temp")

        self.start_time = None
        self.output_path = None

        # Configuration MSS pour la capture d'écran
        self.sct = mss.mss()
        self.monitor = self._get_monitor_from_resolution(resolution)

        # Configuration Audio
        self.audio_format = pyaudio.paInt16
        self.channels = 2
        self.sample_rate = 44100
        self.chunk_size = 1024
```

Ajouter `_write_frame` (cœur testable, ouvre le writer paresseusement) :

```python
    def _write_frame(self, frame_bgr):
        """Applique la chaîne de filtres puis écrit la frame sur disque."""
        frame_bgr = self.filter_chain.process(frame_bgr)

        if self._writer is None:
            Path(self._temp_dir).mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._raw_video_path = str(
                Path(self._temp_dir) / f"lumina_raw_{timestamp}.avi")
            h, w = frame_bgr.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            self._writer = cv2.VideoWriter(
                self._raw_video_path, fourcc, self.fps, (w, h))

        self._writer.write(frame_bgr)
        self._frame_count += 1
```

Remplacer `_capture_screen` (la boucle appelle `_write_frame` au lieu d'append) :

```python
    def _capture_screen(self):
        """Boucle de capture d'écran — écriture disque en continu."""
        frame_interval = 1.0 / self.fps

        while self.is_recording:
            start_frame_time = time.time()

            screenshot = self.sct.grab(self.monitor)
            img = np.array(screenshot)
            img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            self._write_frame(img_bgr)

            elapsed = time.time() - start_frame_time
            sleep_time = max(0, frame_interval - elapsed)
            time.sleep(sleep_time)
```

Remplacer `start_recording` (réinitialisation du nouvel état) :

```python
    def start_recording(self, output_path: str) -> bool:
        """Démarre l'enregistrement"""
        if self.is_recording:
            print("[Lumina] Enregistrement déjà en cours.")
            return False

        self.output_path = output_path
        self.is_recording = True
        self.audio_frames = []
        self._writer = None
        self._raw_video_path = ""
        self._frame_count = 0
        self.start_time = datetime.now()

        print(f"[Lumina] Démarrage de l'enregistrement : "
              f"{self.resolution} @ {self.fps} FPS")

        self.recording_thread = threading.Thread(target=self._capture_screen)
        self.recording_thread.daemon = True
        self.recording_thread.start()

        if self.audio_enabled:
            self.audio_thread = threading.Thread(target=self._capture_audio)
            self.audio_thread.daemon = True
            self.audio_thread.start()

        return True
```

Remplacer `stop_recording` et **supprimer `_save_raw_frames`** :

```python
    def stop_recording(self) -> Optional[Tuple[str, str]]:
        """Arrête l'enregistrement, retourne (chemin vidéo brute, chemin audio)."""
        if not self.is_recording:
            return None

        self.is_recording = False

        if self.recording_thread:
            self.recording_thread.join(timeout=2.0)
        if self.audio_thread:
            self.audio_thread.join(timeout=2.0)

        if self._writer is not None:
            self._writer.release()
            self._writer = None

        if self.start_time:
            duration = (datetime.now() - self.start_time).total_seconds()
            print(f"[Lumina] Enregistrement arrêté. Durée: {duration:.2f}s, "
                  f"Frames: {self._frame_count}")

        raw_video_path = self._raw_video_path if self._frame_count > 0 else ""
        raw_audio_path = self._save_raw_audio() if self.audio_enabled else ""

        return raw_video_path, raw_audio_path
```

Dans `_save_raw_audio`, remplacer les deux premières lignes pour utiliser `self._temp_dir` et retourner `""` (déjà le cas) :

```python
        if not self.audio_frames:
            return ""

        temp_dir = Path(self._temp_dir)
        temp_dir.mkdir(exist_ok=True)
```

(le reste de `_save_raw_audio` est inchangé — remplacer seulement `temp_dir = Path(os.getcwd()) / "temp"` par `temp_dir = Path(self._temp_dir)`).

- [ ] **Step 4 : Vérifier le succès**

Run : `python -m pytest tests/test_recorder_core.py tests/test_filter_chain.py -v`
Attendu : tous PASS (non-régression Task 1 incluse).

- [ ] **Step 5 : Test manuel de fumée (capture réelle, 3 secondes)**

```powershell
python -c "import sys; sys.path.insert(0, 'src'); from core.recorder_core import RecorderCore; import time; r = RecorderCore(fps=10, audio_enabled=False); r.start_recording('ignore.mp4'); time.sleep(3); print(r.stop_recording())"
```

Attendu : chemin `temp\lumina_raw_*.avi` affiché, fichier lisible, RAM stable.

- [ ] **Step 6 : Commit**

```powershell
git add src/core/recorder_core.py tests/test_recorder_core.py
git commit -m "feat: ecriture disque en continu et chaine de filtres dans RecorderCore"
```

---

### Task 4 : PostProcessor — interface + runner qui n'échoue jamais

**Files:**
- Create: `LuminaRecorder/src/postprocess/__init__.py`
- Create: `LuminaRecorder/src/postprocess/base.py`
- Test: `LuminaRecorder/tests/test_postprocess_base.py`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `PostProcessResult` (dataclass) : `name: str`, `success: bool`, `output_path: Optional[str] = None`, `error: Optional[str] = None`.
  - `PostProcessor` (ABC) : attribut `name: str`, méthode abstraite `run(self, video_path: str, audio_path: Optional[str], progress_cb: Callable[[float], None]) -> PostProcessResult`.
  - `run_postprocessors(processors: List[PostProcessor], video_path: str, audio_path: Optional[str], progress_cb: Callable[[float], None], step_cb: Optional[Callable[[str], None]] = None) -> List[PostProcessResult]` — exécute en série, capture toute exception en `PostProcessResult(success=False, error=...)`, appelle `step_cb(nom)` avant chaque processeur ; `progress_cb` reçoit la progression globale 0.0→1.0 (chaque processeur pèse 1/N).

- [ ] **Step 1 : Écrire les tests qui échouent**

`tests/test_postprocess_base.py` :

```python
from postprocess.base import PostProcessor, PostProcessResult, run_postprocessors


class OkProcessor(PostProcessor):
    name = "ok"

    def run(self, video_path, audio_path, progress_cb):
        progress_cb(1.0)
        return PostProcessResult(name=self.name, success=True,
                                 output_path="out.srt")


class BoomProcessor(PostProcessor):
    name = "boom"

    def run(self, video_path, audio_path, progress_cb):
        raise RuntimeError("explosion")


def test_runner_collects_results_in_order():
    results = run_postprocessors([OkProcessor(), OkProcessor()],
                                 "v.mp4", "a.wav", lambda p: None)
    assert [r.success for r in results] == [True, True]


def test_runner_never_raises_and_continues_after_failure():
    results = run_postprocessors([BoomProcessor(), OkProcessor()],
                                 "v.mp4", "a.wav", lambda p: None)
    assert results[0].success is False
    assert "explosion" in results[0].error
    assert results[1].success is True


def test_runner_reports_global_progress_and_steps():
    progress, steps = [], []
    run_postprocessors([OkProcessor(), OkProcessor()], "v.mp4", None,
                       progress.append, step_cb=steps.append)
    assert steps == ["ok", "ok"]
    assert progress[-1] == 1.0
    assert all(0.0 <= p <= 1.0 for p in progress)
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `python -m pytest tests/test_postprocess_base.py -v`
Attendu : FAIL — module inexistant.

- [ ] **Step 3 : Implémenter**

`src/postprocess/base.py` :

```python
"""
Lumina PostProcess - Traitements appliqués après l'arrêt de l'enregistrement.

Règle d'or : le runner n'échoue jamais. Un processeur qui lève une
exception produit un PostProcessResult(success=False) et on passe au
suivant — le fichier original n'est jamais perdu ni modifié.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass
class PostProcessResult:
    name: str
    success: bool
    output_path: Optional[str] = None
    error: Optional[str] = None


class PostProcessor(ABC):
    """Traitement post-enregistrement produisant un fichier séparé."""

    name: str = "postprocessor"

    @abstractmethod
    def run(self, video_path: str, audio_path: Optional[str],
            progress_cb: Callable[[float], None]) -> PostProcessResult:
        ...


def run_postprocessors(processors: List[PostProcessor], video_path: str,
                       audio_path: Optional[str],
                       progress_cb: Callable[[float], None],
                       step_cb: Optional[Callable[[str], None]] = None
                       ) -> List[PostProcessResult]:
    results: List[PostProcessResult] = []
    total = len(processors)

    for i, proc in enumerate(processors):
        if step_cb:
            step_cb(proc.name)

        def scoped_progress(p, _i=i):
            progress_cb(min(1.0, (_i + max(0.0, min(1.0, p))) / total))

        try:
            result = proc.run(video_path, audio_path, scoped_progress)
        except Exception as e:
            result = PostProcessResult(name=proc.name, success=False,
                                       error=str(e))
        results.append(result)
        progress_cb(min(1.0, (i + 1) / total))

    return results
```

`src/postprocess/__init__.py` :

```python
"""Lumina PostProcess - Traitements post-enregistrement."""

from .base import PostProcessor, PostProcessResult, run_postprocessors

__all__ = ['PostProcessor', 'PostProcessResult', 'run_postprocessors']
```

- [ ] **Step 4 : Vérifier le succès**

Run : `python -m pytest tests/test_postprocess_base.py -v`
Attendu : 3 PASS.

- [ ] **Step 5 : Commit**

```powershell
git add src/postprocess tests/test_postprocess_base.py
git commit -m "feat: interface PostProcessor et runner tolerant aux echecs"
```

---

### Task 5 : SubtitlesProcessor (Whisper → .srt)

**Files:**
- Create: `LuminaRecorder/src/postprocess/subtitles_processor.py`
- Modify: `LuminaRecorder/src/postprocess/__init__.py`
- Test: `LuminaRecorder/tests/test_subtitles_processor.py`

**Interfaces:**
- Consumes: `PostProcessor`, `PostProcessResult` (Task 4) ; `ai.whisper_transcriber.WhisperTranscriber` (non modifié).
- Produces:
  - `SubtitlesProcessor(model_size="base", language=None, transcriber=None)` — `name = "Sous-titres"`. Le paramètre `transcriber` permet l'injection pour les tests. `run` transcrit le WAV et écrit `<video_sans_ext>.srt` à côté de la vidéo.
  - `whisper_is_available() -> bool` (fonction module) : True si `faster_whisper` ou `whisper` est importable — utilisée par la UI pour griser la case.

- [ ] **Step 1 : Écrire les tests qui échouent**

`tests/test_subtitles_processor.py` :

```python
from pathlib import Path

from postprocess.subtitles_processor import (SubtitlesProcessor,
                                             whisper_is_available)
from ai.whisper_transcriber import WhisperTranscriber, SubtitleSegment


class FakeTranscriber:
    """Simule un WhisperTranscriber disponible avec 2 segments."""
    is_available = True

    def transcribe(self, audio_path, progress_callback=None):
        self.segments = [
            SubtitleSegment(0, 0.0, 2.0, "Bonjour"),
            SubtitleSegment(1, 2.5, 4.0, "Au revoir"),
        ]
        return True

    def export_srt(self, output_path):
        # Réutilise l'export réel pour produire un vrai SRT
        real = WhisperTranscriber.__new__(WhisperTranscriber)
        real.segments = self.segments
        return WhisperTranscriber.export_srt(real, output_path)


def test_produces_srt_next_to_video(tmp_path):
    video = tmp_path / "Lumina_test.mp4"
    video.write_bytes(b"fake")
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"fake")

    proc = SubtitlesProcessor(transcriber=FakeTranscriber())
    result = proc.run(str(video), str(audio), lambda p: None)

    assert result.success is True
    expected = tmp_path / "Lumina_test.srt"
    assert result.output_path == str(expected)
    content = expected.read_text(encoding="utf-8")
    assert "Bonjour" in content and "-->" in content


def test_fails_cleanly_without_audio(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    proc = SubtitlesProcessor(transcriber=FakeTranscriber())
    result = proc.run(str(video), None, lambda p: None)
    assert result.success is False
    assert result.error


def test_whisper_is_available_returns_bool():
    assert isinstance(whisper_is_available(), bool)
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `python -m pytest tests/test_subtitles_processor.py -v`
Attendu : FAIL — module inexistant.

- [ ] **Step 3 : Implémenter**

`src/postprocess/subtitles_processor.py` :

```python
"""Post-processeur : sous-titres automatiques via Whisper → fichier .srt."""

import importlib.util
import os
from pathlib import Path
from typing import Callable, Optional

from ai.whisper_transcriber import WhisperTranscriber
from .base import PostProcessor, PostProcessResult


def whisper_is_available() -> bool:
    """True si faster-whisper ou whisper est installé (pour griser la case UI)."""
    return (importlib.util.find_spec("faster_whisper") is not None
            or importlib.util.find_spec("whisper") is not None)


class SubtitlesProcessor(PostProcessor):
    name = "Sous-titres"

    def __init__(self, model_size: str = "base",
                 language: Optional[str] = None, transcriber=None):
        self.model_size = model_size
        self.language = language
        self._transcriber = transcriber  # injection pour les tests

    def run(self, video_path: str, audio_path: Optional[str],
            progress_cb: Callable[[float], None]) -> PostProcessResult:
        if not audio_path or not os.path.exists(audio_path):
            return PostProcessResult(
                name=self.name, success=False,
                error="Pas de piste audio à transcrire")

        transcriber = self._transcriber or WhisperTranscriber(
            model_size=self.model_size, language=self.language)

        if not transcriber.is_available:
            return PostProcessResult(
                name=self.name, success=False,
                error="Whisper non installé (pip install faster-whisper)")

        progress_cb(0.1)
        if not transcriber.transcribe(audio_path,
                                      progress_callback=progress_cb):
            return PostProcessResult(name=self.name, success=False,
                                     error="Échec de la transcription")

        srt_path = str(Path(video_path).with_suffix('.srt'))
        if not transcriber.export_srt(srt_path):
            return PostProcessResult(name=self.name, success=False,
                                     error="Échec de l'export SRT")

        progress_cb(1.0)
        return PostProcessResult(name=self.name, success=True,
                                 output_path=srt_path)
```

Mettre à jour `src/postprocess/__init__.py` :

```python
"""Lumina PostProcess - Traitements post-enregistrement."""

from .base import PostProcessor, PostProcessResult, run_postprocessors
from .subtitles_processor import SubtitlesProcessor, whisper_is_available

__all__ = ['PostProcessor', 'PostProcessResult', 'run_postprocessors',
           'SubtitlesProcessor', 'whisper_is_available']
```

- [ ] **Step 4 : Vérifier le succès**

Run : `python -m pytest tests/test_subtitles_processor.py -v`
Attendu : 3 PASS.

- [ ] **Step 5 : Commit**

```powershell
git add src/postprocess tests/test_subtitles_processor.py
git commit -m "feat: post-processeur sous-titres Whisper vers SRT"
```

---

### Task 6 : MagicCutProcessor — coupes réelles via FFmpeg

**Files:**
- Create: `LuminaRecorder/src/postprocess/magic_cut_processor.py`
- Modify: `LuminaRecorder/src/postprocess/__init__.py`
- Test: `LuminaRecorder/tests/test_magic_cut_processor.py`

**Interfaces:**
- Consumes: `PostProcessor`, `PostProcessResult` (Task 4) ; `ai.magic_cut.MagicCutEngine` (non modifié) ; `core.encoder.VideoEncoder._find_ffmpeg` (réutilisé pour localiser ffmpeg).
- Produces:
  - `MagicCutProcessor(silence_threshold=0.02, min_silence_duration=0.5, max_silence_duration=3.0)` — `name = "Magic Cut"`. `run` détecte les silences sur le WAV, puis produit `<video_sans_ext>_cut.mp4` en concaténant les segments à garder via FFmpeg (`filter_complex` trim/atrim + concat).
  - Fonction module `build_ffmpeg_cut_command(ffmpeg: str, input_path: str, segments: List[Tuple[float, float]], output_path: str, has_audio: bool) -> List[str]` (pure, testable sans FFmpeg).

- [ ] **Step 1 : Écrire les tests qui échouent**

`tests/test_magic_cut_processor.py` :

```python
import shutil
import subprocess
import wave

import numpy as np
import pytest

from postprocess.magic_cut_processor import (MagicCutProcessor,
                                             build_ffmpeg_cut_command)

FFMPEG = shutil.which("ffmpeg")


def test_build_command_two_segments_with_audio():
    cmd = build_ffmpeg_cut_command(
        "ffmpeg", "in.mp4", [(0.0, 2.0), (3.0, 5.0)], "out.mp4",
        has_audio=True)
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert "-filter_complex" in cmd
    assert "trim=start=0.0:end=2.0" in joined
    assert "atrim=start=3.0:end=5.0" in joined
    assert "concat=n=2:v=1:a=1" in joined
    assert cmd[-1] == "out.mp4"


def test_build_command_video_only():
    cmd = build_ffmpeg_cut_command(
        "ffmpeg", "in.mp4", [(0.0, 1.0)], "out.mp4", has_audio=False)
    joined = " ".join(cmd)
    assert "concat=n=1:v=1:a=0" in joined
    assert "atrim" not in joined


def _write_wav_with_silences(path, duration=10.0, rate=8000):
    """Signal 440 Hz avec silences à 2-3s, 5-6s, 7.5-8.5s (générateur du spec)."""
    t = np.linspace(0, duration, int(rate * duration))
    audio = (np.sin(2 * np.pi * 440 * t) * 12000).astype(np.int16)
    audio[int(rate * 2):int(rate * 3)] = 0
    audio[int(rate * 5):int(rate * 6)] = 0
    audio[int(rate * 7.5):int(rate * 8.5)] = 0
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(audio.tobytes())


@pytest.mark.skipif(FFMPEG is None, reason="FFmpeg absent du PATH")
def test_end_to_end_cut_shortens_video(tmp_path):
    # Vidéo synthétique 10 s (couleur unie) générée par FFmpeg
    video = tmp_path / "in.mp4"
    subprocess.run([FFMPEG, "-y", "-f", "lavfi", "-i",
                    "color=c=blue:s=160x120:d=10", "-r", "10",
                    str(video)], check=True, capture_output=True)
    audio = tmp_path / "in.wav"
    _write_wav_with_silences(audio)

    proc = MagicCutProcessor(silence_threshold=0.02,
                             min_silence_duration=0.5,
                             max_silence_duration=3.0)
    result = proc.run(str(video), str(audio), lambda p: None)

    assert result.success is True
    out = tmp_path / "in_cut.mp4"
    assert result.output_path == str(out)
    probe = subprocess.run(
        [FFMPEG.replace("ffmpeg", "ffprobe"), "-v", "quiet",
         "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True)
    duration = float(probe.stdout.strip())
    assert duration < 9.0  # ~3 s de silences retirés sur 10 s


def test_no_silences_returns_success_without_output(tmp_path):
    """Audio plein signal : rien à couper, succès avec message, pas de fichier."""
    audio = tmp_path / "full.wav"
    rate = 8000
    t = np.linspace(0, 4.0, rate * 4)
    sig = (np.sin(2 * np.pi * 440 * t) * 12000).astype(np.int16)
    with wave.open(str(audio), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(sig.tobytes())

    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake")
    proc = MagicCutProcessor()
    result = proc.run(str(video), str(audio), lambda p: None)
    assert result.success is True
    assert result.output_path is None  # rien coupé, original conservé
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `python -m pytest tests/test_magic_cut_processor.py -v`
Attendu : FAIL — module inexistant.

- [ ] **Step 3 : Implémenter**

`src/postprocess/magic_cut_processor.py` :

```python
"""
Post-processeur Magic Cut : détecte les silences (MagicCutEngine) et
produit une vidéo raccourcie via FFmpeg (trim/atrim + concat).
Le fichier original n'est jamais modifié : sortie dans <nom>_cut.mp4.
"""

import os
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from ai.magic_cut import MagicCutEngine
from core.encoder import VideoEncoder
from .base import PostProcessor, PostProcessResult


def build_ffmpeg_cut_command(ffmpeg: str, input_path: str,
                             segments: List[Tuple[float, float]],
                             output_path: str,
                             has_audio: bool) -> List[str]:
    """Construit la commande FFmpeg concaténant les segments à garder."""
    parts = []
    for i, (start, end) in enumerate(segments):
        parts.append(f"[0:v]trim=start={start}:end={end},"
                     f"setpts=PTS-STARTPTS[v{i}]")
        if has_audio:
            parts.append(f"[0:a]atrim=start={start}:end={end},"
                         f"asetpts=PTS-STARTPTS[a{i}]")

    n = len(segments)
    if has_audio:
        inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{inputs}concat=n={n}:v=1:a=1[outv][outa]")
        maps = ["-map", "[outv]", "-map", "[outa]"]
    else:
        inputs = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{inputs}concat=n={n}:v=1:a=0[outv]")
        maps = ["-map", "[outv]"]

    return [ffmpeg, "-y", "-i", input_path,
            "-filter_complex", ";".join(parts)] + maps + [output_path]


class MagicCutProcessor(PostProcessor):
    name = "Magic Cut"

    def __init__(self, silence_threshold: float = 0.02,
                 min_silence_duration: float = 0.5,
                 max_silence_duration: float = 3.0):
        self.silence_threshold = silence_threshold
        self.min_silence_duration = min_silence_duration
        self.max_silence_duration = max_silence_duration

    def run(self, video_path: str, audio_path: Optional[str],
            progress_cb: Callable[[float], None]) -> PostProcessResult:
        if not audio_path or not os.path.exists(audio_path):
            return PostProcessResult(
                name=self.name, success=False,
                error="Pas de piste audio pour détecter les silences")

        engine = MagicCutEngine(
            silence_threshold=self.silence_threshold,
            min_silence_duration=self.min_silence_duration,
            max_silence_duration=self.max_silence_duration)

        if not engine.load_audio_file(audio_path):
            return PostProcessResult(name=self.name, success=False,
                                     error="Impossible de lire l'audio")
        progress_cb(0.2)

        silences = engine.detect_silences()
        if not silences:
            return PostProcessResult(name=self.name, success=True,
                                     output_path=None,
                                     error="Aucun silence à couper")
        progress_cb(0.4)

        segments = engine.get_trimmed_segments()
        if not segments or len(segments) == 0:
            return PostProcessResult(name=self.name, success=True,
                                     output_path=None,
                                     error="Aucun segment à conserver")

        try:
            ffmpeg = VideoEncoder()._find_ffmpeg()
        except FileNotFoundError as e:
            return PostProcessResult(name=self.name, success=False,
                                     error=str(e))

        output_path = str(Path(video_path).with_name(
            Path(video_path).stem + "_cut.mp4"))
        # La vidéo finale (post-fusion) contient l'audio
        cmd = build_ffmpeg_cut_command(ffmpeg, video_path, segments,
                                       output_path, has_audio=True)
        progress_cb(0.5)

        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=3600)
        if proc.returncode != 0:
            # Retente sans piste audio (vidéo sans son)
            cmd = build_ffmpeg_cut_command(ffmpeg, video_path, segments,
                                           output_path, has_audio=False)
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=3600)
            if proc.returncode != 0:
                return PostProcessResult(
                    name=self.name, success=False,
                    error=f"FFmpeg a échoué: {proc.stderr[-300:]}")

        progress_cb(1.0)
        return PostProcessResult(name=self.name, success=True,
                                 output_path=output_path)
```

Mettre à jour `src/postprocess/__init__.py` :

```python
"""Lumina PostProcess - Traitements post-enregistrement."""

from .base import PostProcessor, PostProcessResult, run_postprocessors
from .subtitles_processor import SubtitlesProcessor, whisper_is_available
from .magic_cut_processor import MagicCutProcessor

__all__ = ['PostProcessor', 'PostProcessResult', 'run_postprocessors',
           'SubtitlesProcessor', 'whisper_is_available',
           'MagicCutProcessor']
```

- [ ] **Step 4 : Vérifier le succès**

Run : `python -m pytest tests/test_magic_cut_processor.py -v`
Attendu : 4 PASS (ou 3 PASS + 1 SKIP si FFmpeg absent).

- [ ] **Step 5 : Commit**

```powershell
git add src/postprocess tests/test_magic_cut_processor.py
git commit -m "feat: Magic Cut applique les coupes reelles via FFmpeg"
```

---

### Task 7 : UI — carte « Options IA », persistance config, préflight FFmpeg, branchement des filtres

**Files:**
- Modify: `LuminaRecorder/src/ui/main_window.py`
- Test: `LuminaRecorder/tests/test_ai_options_config.py`

**Interfaces:**
- Consumes: `ConfigManager` (existant), filtres (Task 2), `RecorderCore(filters=..., on_filter_disabled=...)` (Task 3), `whisper_is_available` (Task 5).
- Produces:
  - Classe utilitaire `AIOptions` dans `main_window.py` (logique pure, testable sans tkinter) :
    - `AIOptions.load(config: ConfigManager) -> dict` — retourne `{'privacy_blur': bool, 'clean_canvas': bool, 'overlay': bool, 'subtitles': bool, 'magic_cut': bool}` depuis les clés existantes du .ini : `[privacy] dynamic_blur`, `[ai] clean_canvas`, `[system] show_overlay`, `[ai] auto_subtitles`, `[ai] magic_cut` (défaut False partout).
    - `AIOptions.save(config: ConfigManager, options: dict) -> None` — écrit les mêmes clés.
    - `AIOptions.build_filters(options: dict) -> list` — liste de `FrameFilter` selon les cases temps réel cochées.
    - `AIOptions.build_postprocessors(options: dict) -> list` — liste de `PostProcessor` (ordre : sous-titres puis Magic Cut).
  - `MainWindow` : carte « 🤖 Options IA » (5 Checkbuttons), préflight FFmpeg avant démarrage, passage des filtres au `RecorderCore`.

- [ ] **Step 1 : Écrire les tests qui échouent (logique AIOptions, sans tkinter)**

`tests/test_ai_options_config.py` :

```python
from utils.config_manager import ConfigManager
from ui.main_window import AIOptions
from filters.privacy_blur_filter import PrivacyBlurFilter
from postprocess.subtitles_processor import SubtitlesProcessor
from postprocess.magic_cut_processor import MagicCutProcessor


def make_config(tmp_path):
    return ConfigManager(config_path=str(tmp_path / "test_config.ini"))


def test_load_defaults_all_false(tmp_path):
    cfg = make_config(tmp_path)
    opts = AIOptions.load(cfg)
    assert opts == {'privacy_blur': False, 'clean_canvas': False,
                    'overlay': False, 'subtitles': False,
                    'magic_cut': False}


def test_save_then_load_roundtrip(tmp_path):
    cfg = make_config(tmp_path)
    wanted = {'privacy_blur': True, 'clean_canvas': False,
              'overlay': True, 'subtitles': True, 'magic_cut': False}
    AIOptions.save(cfg, wanted)
    cfg2 = ConfigManager(config_path=str(tmp_path / "test_config.ini"))
    assert AIOptions.load(cfg2) == wanted


def test_build_filters_matches_checked_options():
    opts = {'privacy_blur': True, 'clean_canvas': False,
            'overlay': False, 'subtitles': False, 'magic_cut': False}
    filters = AIOptions.build_filters(opts)
    assert len(filters) == 1
    assert isinstance(filters[0], PrivacyBlurFilter)


def test_build_postprocessors_order_subtitles_first():
    opts = {'privacy_blur': False, 'clean_canvas': False,
            'overlay': False, 'subtitles': True, 'magic_cut': True}
    procs = AIOptions.build_postprocessors(opts)
    assert isinstance(procs[0], SubtitlesProcessor)
    assert isinstance(procs[1], MagicCutProcessor)
```

- [ ] **Step 2 : Vérifier l'échec**

Run : `python -m pytest tests/test_ai_options_config.py -v`
Attendu : FAIL — `AIOptions` inexistante. (NB : l'import de `ui.main_window` importe tkinter mais n'ouvre aucune fenêtre — OK.)

- [ ] **Step 3 : Implémenter `AIOptions` dans `main_window.py`**

En haut de `src/ui/main_window.py`, ajouter aux imports :

```python
from utils.config_manager import ConfigManager
from filters.privacy_blur_filter import PrivacyBlurFilter
from filters.clean_canvas_filter import CleanCanvasFilter
from filters.overlay_filter import OverlayFilter
from postprocess.subtitles_processor import (SubtitlesProcessor,
                                             whisper_is_available)
from postprocess.magic_cut_processor import MagicCutProcessor
from postprocess.base import run_postprocessors
```

Ajouter la classe avant `MainWindow` :

```python
class AIOptions:
    """Logique des Options IA : persistance .ini et construction des
    filtres/post-processeurs. Séparée de la UI pour être testable."""

    # (clé_option) -> (section_ini, clé_ini)
    KEYS = {
        'privacy_blur': ('privacy', 'dynamic_blur'),
        'clean_canvas': ('ai', 'clean_canvas'),
        'overlay': ('system', 'show_overlay'),
        'subtitles': ('ai', 'auto_subtitles'),
        'magic_cut': ('ai', 'magic_cut'),
    }

    @staticmethod
    def load(config: ConfigManager) -> dict:
        return {opt: config.get_bool(section, key, fallback=False)
                for opt, (section, key) in AIOptions.KEYS.items()}

    @staticmethod
    def save(config: ConfigManager, options: dict) -> None:
        for opt, (section, key) in AIOptions.KEYS.items():
            config.set(section, key, options.get(opt, False))

    @staticmethod
    def build_filters(options: dict) -> list:
        filters = []
        if options.get('privacy_blur'):
            filters.append(PrivacyBlurFilter())
        if options.get('clean_canvas'):
            filters.append(CleanCanvasFilter())
        if options.get('overlay'):
            filters.append(OverlayFilter())
        return filters

    @staticmethod
    def build_postprocessors(options: dict) -> list:
        procs = []
        if options.get('subtitles'):
            procs.append(SubtitlesProcessor())   # sous-titres AVANT Magic Cut
        if options.get('magic_cut'):
            procs.append(MagicCutProcessor())
        return procs
```

- [ ] **Step 4 : Vérifier le succès des tests AIOptions**

Run : `python -m pytest tests/test_ai_options_config.py -v`
Attendu : 4 PASS.

- [ ] **Step 5 : Câbler la UI (carte, préflight, filtres)**

Toujours dans `main_window.py` :

**a)** Dans `MainWindow.__init__`, après `self.recommended_settings = ...`, ajouter :

```python
        self.config = ConfigManager()
        self.ai_options = AIOptions.load(self.config)
```

**b)** Dans `_build_ui`, après la carte Audio (`self.volume_slider.pack(pady=10)`), ajouter la 4e carte :

```python
        # Carte 4: Options IA
        ai_card = ConfigCard(config_container, text="🤖 Options IA")
        ai_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10)

        self.ai_vars = {}
        labels = [
            ('privacy_blur', "Flou confidentialité"),
            ('clean_canvas', "Masquer notifications"),
            ('overlay', "Overlay métriques"),
            ('subtitles', "Sous-titres auto"),
            ('magic_cut', "Couper les silences"),
        ]
        for key, label in labels:
            var = tk.BooleanVar(value=self.ai_options.get(key, False))
            cb = tk.Checkbutton(ai_card, text=label, variable=var,
                                bg=self.colors['bg_secondary'],
                                fg=self.colors['text_primary'],
                                anchor='w',
                                command=self._on_ai_option_changed)
            state = tk.NORMAL
            if key == 'subtitles' and not whisper_is_available():
                state = tk.DISABLED
                cb.config(text=label + " (installer faster-whisper)")
            cb.config(state=state)
            cb.pack(fill=tk.X, padx=5)
            self.ai_vars[key] = var
```

**c)** Ajouter la méthode de persistance :

```python
    def _on_ai_option_changed(self):
        """Sauvegarde immédiate des Options IA dans le .ini"""
        self.ai_options = {k: v.get() for k, v in self.ai_vars.items()}
        AIOptions.save(self.config, self.ai_options)
```

**d)** Dans `_start_recording`, AVANT la création du recorder, ajouter le préflight FFmpeg :

```python
        # Préflight : FFmpeg doit être disponible AVANT de démarrer
        try:
            VideoEncoder()
        except FileNotFoundError as e:
            messagebox.showerror("FFmpeg manquant", str(e))
            return
```

**e)** Toujours dans `_start_recording`, remplacer la création du recorder :

```python
        options = {k: v.get() for k, v in self.ai_vars.items()}
        self.recorder = RecorderCore(
            resolution=resolution_str,
            fps=fps,
            audio_enabled=True,
            audio_gain=audio_gain,
            filters=AIOptions.build_filters(options),
            on_filter_disabled=self._on_filter_disabled
        )
```

**f)** Ajouter le callback (thread capture → thread UI via `after`) :

```python
    def _on_filter_disabled(self, filter_name: str):
        """Appelé depuis le thread de capture quand un filtre est trop lent."""
        display = {'privacy_blur': 'Flou confidentialité',
                   'clean_canvas': 'Masquer notifications',
                   'overlay': 'Overlay métriques'}.get(filter_name,
                                                       filter_name)
        self.root.after(0, lambda: self.status_label.config(
            text=f"⚠ {display} désactivé (machine trop lente)",
            fg=self.colors['warning']))
```

- [ ] **Step 6 : Vérification (tests + fumée import)**

Run : `python -m pytest tests/ -v` — tous PASS.
Run : `python -c "import sys; sys.path.insert(0, 'src'); import ui.main_window"` — pas d'erreur d'import.

- [ ] **Step 7 : Vérification manuelle**

Run : `python main.py`
Vérifier : la carte « 🤖 Options IA » apparaît avec 5 cases décochées ; cocher « Overlay métriques », relancer l'app → la case est restée cochée (persistance .ini).

- [ ] **Step 8 : Commit**

```powershell
git add src/ui/main_window.py tests/test_ai_options_config.py
git commit -m "feat: carte Options IA, persistance config et branchement des filtres"
```

---

### Task 8 : UI — post-traitement threadé, fenêtre de progression, résumé final

**Files:**
- Modify: `LuminaRecorder/src/ui/main_window.py` (méthode `_stop_recording` + nouvelles méthodes)

**Interfaces:**
- Consumes: `run_postprocessors`, `AIOptions.build_postprocessors` (Task 7), `PostProcessResult` (Task 4).
- Produces: rien de nouveau pour les autres tâches — c'est la couche finale.

- [ ] **Step 1 : Remplacer la fin de `_stop_recording`**

Dans `_stop_recording`, après le bloc `if success:` de l'encodage FFmpeg, remplacer le contenu du `if success:` par :

```python
                if success:
                    self.status_label.config(text="✓ Enregistrement terminé !",
                                            fg=self.colors['success'])
                    options = {k: v.get() for k, v in self.ai_vars.items()}
                    processors = AIOptions.build_postprocessors(options)
                    if processors:
                        self._run_postprocessing(final_path, processors)
                    else:
                        messagebox.showinfo(
                            "Succès", f"Vidéo sauvegardée :\n{final_path}")
```

**Attention** : l'encodeur supprime les fichiers temporaires (`_cleanup_temp_files`) dont le WAV — or les post-processeurs en ont besoin. Dans `_stop_recording`, AVANT l'appel `encoder.encode(...)`, préserver une copie du WAV si du post-traitement est prévu :

```python
                # Préserver le WAV pour le post-traitement (l'encodeur
                # supprime les temporaires après fusion)
                options = {k: v.get() for k, v in self.ai_vars.items()}
                needs_audio_later = options.get('subtitles') or options.get('magic_cut')
                preserved_audio = None
                if needs_audio_later and self.current_audio_path \
                        and os.path.exists(self.current_audio_path):
                    import shutil
                    preserved_audio = self.current_audio_path + ".keep.wav"
                    shutil.copyfile(self.current_audio_path, preserved_audio)
```

puis passer `preserved_audio` à `_run_postprocessing(final_path, processors, preserved_audio)`.

- [ ] **Step 2 : Ajouter la fenêtre de progression et le thread**

Nouvelles méthodes dans `MainWindow` :

```python
    def _run_postprocessing(self, video_path, processors, audio_path=None):
        """Exécute les post-processeurs dans un thread avec fenêtre de
        progression. La UI n'est jamais gelée ; tkinter n'est touché que
        via root.after."""
        import threading

        progress_win = tk.Toplevel(self.root)
        progress_win.title("Traitement IA en cours...")
        progress_win.geometry("400x120")
        progress_win.transient(self.root)
        progress_win.grab_set()

        step_label = tk.Label(progress_win, text="Préparation...",
                              font=("Segoe UI", 10))
        step_label.pack(pady=(15, 5))
        bar = ttk.Progressbar(progress_win, maximum=1.0, length=350)
        bar.pack(pady=5)

        def on_progress(p):
            self.root.after(0, lambda: bar.config(value=p))

        def on_step(name):
            self.root.after(0, lambda: step_label.config(
                text=f"Étape : {name}..."))

        def worker():
            results = run_postprocessors(processors, video_path,
                                         audio_path, on_progress,
                                         step_cb=on_step)
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)  # copie .keep.wav temporaire
                except OSError:
                    pass
            self.root.after(0, lambda: self._show_postprocess_summary(
                video_path, results, progress_win))

        threading.Thread(target=worker, daemon=True).start()

    def _show_postprocess_summary(self, video_path, results, progress_win):
        """Résumé final : la vidéo est TOUJOURS annoncée comme sauvegardée."""
        progress_win.destroy()
        lines = [f"✓ Vidéo sauvegardée :\n{video_path}\n"]
        for r in results:
            if r.success and r.output_path:
                lines.append(f"✓ {r.name} : {os.path.basename(r.output_path)}")
            elif r.success:
                lines.append(f"✓ {r.name} : {r.error or 'rien à faire'}")
            else:
                lines.append(f"✗ {r.name} échoué : {r.error}")
        messagebox.showinfo("Traitement terminé", "\n".join(lines))
```

- [ ] **Step 3 : Vérification (non-régression complète)**

Run : `python -m pytest tests/ -v` — tous PASS.
Run : `python -c "import sys; sys.path.insert(0, 'src'); import ui.main_window"` — pas d'erreur.

- [ ] **Step 4 : Vérification manuelle de bout en bout**

1. `python main.py`
2. Cocher « Overlay métriques » + « Couper les silences ».
3. Enregistrer ~15 s en parlant avec des pauses de 1-2 s.
4. Arrêter. Vérifier : fenêtre « Traitement IA en cours... » avec barre, puis résumé.
5. Vérifier les fichiers dans `~/Videos/Lumina/` : `Lumina_XXX.mp4` (avec overlay visible) et `Lumina_XXX_cut.mp4` plus courte.
6. Cocher « Sous-titres auto » si faster-whisper installé, sinon vérifier que la case est grisée.

- [ ] **Step 5 : Commit final**

```powershell
git add src/ui/main_window.py
git commit -m "feat: post-traitement threade avec fenetre de progression et resume"
```

---

## Auto-revue (faite à la rédaction)

- **Couverture du spec** : buffer RAM → Task 3 ; chaîne filtres + garde-fou → Tasks 1-3 ; 3 filtres → Task 2 ; post-processeurs + jamais-échouer → Tasks 4-6 ; coupes FFmpeg réelles → Task 6 ; carte UI + persistance + grisage Whisper → Task 7 ; thread + progression + résumé + préflight FFmpeg → Tasks 7-8 ; tests pytest → chaque task. Smart Focus exclu (conforme spec).
- **Types cohérents** : `FrameFilter.process(frame) -> frame`, `PostProcessor.run(video, audio, progress_cb) -> PostProcessResult`, `RecorderCore(filters=..., on_filter_disabled=...)` — mêmes signatures dans toutes les tasks.
- **Pas de placeholders** : chaque étape contient le code réel.
