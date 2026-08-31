"""Post-processeurs qui font appel à un fournisseur IA.

Deux traitements :

- `SummaryProcessor` — résumé et mots-clés de l'enregistrement, écrits
  dans un fichier .md à côté de la vidéo.
- `SubtitleFixProcessor` — corrige un .srt déjà produit par Whisper
  (ponctuation, noms propres, jargon technique).

Confidentialité
---------------
Ces deux traitements envoient le CONTENU PARLÉ de l'enregistrement au
fournisseur configuré. Avec Ollama, tout reste sur la machine ; avec un
service distant, le texte est transmis à un tiers. L'interface le signale
avant activation, et aucun des deux ne s'exécute sans que l'option ait
été cochée explicitement.

Tous deux travaillent à partir du fichier .srt : ils doivent donc
s'exécuter APRÈS SubtitlesProcessor, et se déclarent en échec explicite
s'il est absent — plutôt que de transcrire une seconde fois.
"""

import os
import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from services.ai_engine import LuminaAIEngine
from services.ai_provider import AITasks
from .base import PostProcessor, PostProcessResult


def parse_srt(content: str) -> List[Tuple[str, str, str]]:
    """Découpe un .srt en (numéro, horodatage, texte).

    Le texte d'un bloc peut tenir sur plusieurs lignes ; elles sont
    jointes par un espace, la correction travaillant ligne à ligne.
    """
    blocks = []
    for raw in re.split(r'\n\s*\n', content.strip()):
        lines = [l for l in raw.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        if '-->' not in lines[1]:
            continue
        blocks.append((lines[0].strip(), lines[1].strip(),
                       " ".join(l.strip() for l in lines[2:])))
    return blocks


def build_srt(blocks: List[Tuple[str, str, str]]) -> str:
    """Reconstruit un .srt à partir de blocs (numéro, horodatage, texte)."""
    return "\n\n".join(f"{number}\n{timing}\n{text}"
                       for number, timing, text in blocks) + "\n"


class SummaryProcessor(PostProcessor):
    """Résumé et mots-clés, écrits dans un .md à côté de la vidéo."""

    name = "Résumé IA"

    def __init__(self, ai_engine: Optional[LuminaAIEngine] = None):
        self.ai_engine = ai_engine

    def run(self, video_path: str, audio_path: Optional[str],
            progress_cb: Callable[[float], None]) -> PostProcessResult:
        if self.ai_engine is None:
            return PostProcessResult(
                name=self.name, success=False,
                error="Aucun fournisseur IA configuré")

        srt_path = Path(video_path).with_suffix('.srt')
        if not srt_path.exists():
            # Ne pas transcrire une seconde fois : le dire clairement
            return PostProcessResult(
                name=self.name, success=False,
                error="Nécessite les sous-titres automatiques")

        progress_cb(0.2)
        try:
            blocks = parse_srt(srt_path.read_text(encoding='utf-8'))
        except OSError as e:
            return PostProcessResult(name=self.name, success=False,
                                     error=f"Lecture du .srt : {e}")

        transcript = " ".join(text for _, _, text in blocks).strip()
        if not transcript:
            return PostProcessResult(name=self.name, success=False,
                                     error="Transcription vide")

        progress_cb(0.4)
        summary = AITasks(self.ai_engine).summary(transcript)
        if not summary:
            return PostProcessResult(name=self.name, success=False,
                                     error="Le fournisseur IA n'a rien renvoyé")

        progress_cb(0.9)
        out_path = str(Path(video_path).with_suffix('')) + "_resume.md"
        try:
            Path(out_path).write_text(
                f"# {Path(video_path).stem}\n\n{summary}\n",
                encoding='utf-8')
        except OSError as e:
            return PostProcessResult(name=self.name, success=False,
                                     error=f"Écriture du résumé : {e}")

        progress_cb(1.0)
        return PostProcessResult(name=self.name, success=True,
                                 output_path=out_path)


class SubtitleFixProcessor(PostProcessor):
    """Corrige un .srt existant : ponctuation, noms propres, jargon."""

    name = "Sous-titres corrigés"

    # Au-delà, on découpe : envoyer 400 lignes d'un coup dépasse la
    # fenêtre de contexte des petits modèles, qui renvoient alors un
    # nombre de lignes incorrect et la correction est abandonnée
    BATCH_SIZE = 40

    def __init__(self, ai_engine: Optional[LuminaAIEngine] = None):
        self.ai_engine = ai_engine

    def run(self, video_path: str, audio_path: Optional[str],
            progress_cb: Callable[[float], None]) -> PostProcessResult:
        if self.ai_engine is None:
            return PostProcessResult(
                name=self.name, success=False,
                error="Aucun fournisseur IA configuré")

        srt_path = Path(video_path).with_suffix('.srt')
        if not srt_path.exists():
            return PostProcessResult(
                name=self.name, success=False,
                error="Nécessite les sous-titres automatiques")

        try:
            blocks = parse_srt(srt_path.read_text(encoding='utf-8'))
        except OSError as e:
            return PostProcessResult(name=self.name, success=False,
                                     error=f"Lecture du .srt : {e}")

        if not blocks:
            return PostProcessResult(name=self.name, success=False,
                                     error="Aucun sous-titre à corriger")

        tasks = AITasks(self.ai_engine)
        texts = [text for _, _, text in blocks]
        corrected: List[str] = []

        for start in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[start:start + self.BATCH_SIZE]
            # fix_subtitles renvoie le lot d'origine si le modèle ne
            # respecte pas le nombre de lignes : les horodatages restent
            # alignés quoi qu'il arrive
            corrected.extend(tasks.fix_subtitles(batch))
            progress_cb(min(0.95, (start + len(batch)) / len(texts)))

        if corrected == texts:
            # Rien n'a changé : ne pas écrire un fichier identique qui
            # laisserait croire à une correction effective
            return PostProcessResult(
                name=self.name, success=True,
                error="Aucune correction nécessaire")

        out_path = str(Path(video_path).with_suffix('')) + "_corrige.srt"
        fixed = [(number, timing, text)
                 for (number, timing, _), text in zip(blocks, corrected)]
        try:
            Path(out_path).write_text(build_srt(fixed), encoding='utf-8')
        except OSError as e:
            return PostProcessResult(name=self.name, success=False,
                                     error=f"Écriture du .srt corrigé : {e}")

        progress_cb(1.0)
        return PostProcessResult(name=self.name, success=True,
                                 output_path=out_path)
