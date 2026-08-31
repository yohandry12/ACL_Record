"""
Whisper Transcription - Sous-titres Automatiques

Utilise le modèle Whisper d'OpenAI (ou alternative locale) pour :
- Transcrire automatiquement l'audio en texte
- Générer des sous-titres synchronisés (.srt, .vtt)
- Support multi-langues avec détection automatique
- Ponctuation et mise en forme intelligentes

Formats de sortie supportés :
- SRT (SubRip) - Compatible tous lecteurs
- VTT (WebVTT) - Pour le web
- TXT - Transcription brute
- JSON - Données structurées pour édition
"""

import os
import sys
from typing import List, Optional, Dict
from dataclasses import dataclass
import json


@dataclass
class SubtitleSegment:
    """Représente un segment de sous-titre"""
    index: int
    start_time: float  # en secondes
    end_time: float    # en secondes
    text: str
    language: Optional[str] = None


class WhisperTranscriber:
    """
    Moteur de transcription utilisant Whisper
    
    Supporte :
    - whisper (officiel OpenAI)
    - faster-whisper (optimisé CPU/GPU)
    - whisper.cpp (léger, C++)
    
    Fallback vers une simulation si non installé
    """
    
    def __init__(
        self,
        model_size: str = "base",
        language: Optional[str] = None,
        device: str = "cpu"
    ):
        """
        Args:
            model_size: Taille du modèle ('tiny', 'base', 'small', 'medium', 'large')
            language: Code langue (ex: 'fr', 'en') ou None pour auto-détection
            device: 'cpu' ou 'cuda' pour GPU NVIDIA
        """
        self.model_size = model_size
        self.language = language
        self.device = device
        
        self.model = None
        self.is_available = False
        self.segments: List[SubtitleSegment] = []
        
        # Tentative d'import de whisper
        self._try_import_whisper()
    
    def _try_import_whisper(self):
        """Tente d'importer whisper, marque comme indisponible si échec"""
        try:
            # Essayer faster-whisper en premier (plus rapide)
            try:
                from faster_whisper import WhisperModel
                self.whisper_lib = "faster-whisper"
                self.model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type="int8" if self.device == "cpu" else "float16"
                )
                self.is_available = True
                print(f"✓ faster-whisper chargé ({self.model_size})")
                return
            except ImportError:
                pass
            
            # Essayer whisper officiel
            import whisper
            self.whisper_lib = "whisper"
            self.model = whisper.load_model(self.model_size, device=self.device)
            self.is_available = True
            print(f"✓ whisper chargé ({self.model_size})")
            
        except ImportError:
            print("⚠ Whisper non installé. Transcription simulée.")
            print("  Pour activer: pip install openai-whisper")
            print("  Ou: pip install faster-whisper (recommandé)")
            self.is_available = False
    
    def _collect_segments(self, segments, info, progress_callback=None):
        """Range les segments Whisper dans self.segments."""
        self.segments = []
        for i, segment in enumerate(segments):
            self.segments.append(SubtitleSegment(
                index=i,
                start_time=segment.start,
                end_time=segment.end,
                text=segment.text.strip(),
                language=info.language
            ))
            if progress_callback:
                # Progression approximative
                progress_callback(min(0.9, 0.2 + (i * 0.01)))

    def transcribe(self, audio_path: str, progress_callback=None) -> bool:
        """
        Transcrit un fichier audio en sous-titres
        
        Args:
            audio_path: Chemin vers le fichier audio
            progress_callback: Fonction callback pour la progression (0.0 à 1.0)
            
        Returns:
            True si succès, False sinon
        """
        if not os.path.exists(audio_path):
            print(f"Fichier audio non trouvé: {audio_path}")
            return False
        
        if not self.is_available:
            # Mode simulation pour test sans whisper
            print("Mode simulation activé")
            return self._simulate_transcription(audio_path)
        
        try:
            if progress_callback:
                progress_callback(0.1)
            
            if self.whisper_lib == "faster-whisper":
                segments, info = self.model.transcribe(
                    audio_path,
                    language=self.language,
                    beam_size=5,
                    vad_filter=True  # Détection de voix active
                )
                self._collect_segments(segments, info, progress_callback)

                if not self.segments:
                    # Constaté sur un enregistrement réel : une voix brève
                    # sur fond sonore, et le VAD écarte TOUT l'audio ;
                    # l'auto-détection de langue, privée de parole, se
                    # trompe et il ne reste aucun segment. Une seconde
                    # passe sans VAD rattrape la parole réellement
                    # présente ; si elle ne trouve rien non plus, il n'y a
                    # vraiment rien à sous-titrer.
                    segments, info = self.model.transcribe(
                        audio_path,
                        language=self.language,
                        beam_size=5,
                        vad_filter=False
                    )
                    self._collect_segments(segments, info, progress_callback)
            
            elif self.whisper_lib == "whisper":
                result = self.model.transcribe(
                    audio_path,
                    language=self.language,
                    verbose=False
                )
                
                self.segments = []
                for i, segment in enumerate(result['segments']):
                    self.segments.append(SubtitleSegment(
                        index=i,
                        start_time=segment['start'],
                        end_time=segment['end'],
                        text=segment['text'].strip(),
                        language=result.get('language')
                    ))
                    
                    if progress_callback:
                        progress_callback(min(0.9, 0.2 + (i * 0.01)))
            
            if progress_callback:
                progress_callback(1.0)
            
            print(f"✓ Transcription terminée: {len(self.segments)} segments")
            return True
            
        except Exception as e:
            print(f"Erreur de transcription: {e}")
            return False
    
    def _simulate_transcription(self, audio_path: str) -> bool:
        """Simulation de transcription pour test sans whisper"""
        import random
        
        phrases_sample = [
            "Bonjour et bienvenue dans ce tutoriel.",
            "Aujourd'hui nous allons découvrir Lumina Recorder.",
            "C'est un outil puissant pour l'enregistrement d'écran.",
            "Il offre une qualité 4K exceptionnelle.",
            "Le volume audio est automatiquement optimisé.",
            "Vous pouvez activer le Smart Focus pour suivre vos actions.",
            "Clean Canvas masque les notifications indésirables.",
            "Magic Cut supprime automatiquement les silences.",
            "L'interface est intuitive et moderne.",
            "Merci d'avoir utilisé Lumina!"
        ]
        
        self.segments = []
        current_time = 0.0
        
        for i, phrase in enumerate(phrases_sample):
            duration = random.uniform(2.0, 4.0)
            pause = random.uniform(0.5, 1.5)
            
            self.segments.append(SubtitleSegment(
                index=i,
                start_time=current_time,
                end_time=current_time + duration,
                text=phrase,
                language='fr'
            ))
            
            current_time += duration + pause
        
        print(f"Simulation: {len(self.segments)} segments générés")
        return True
    
    def export_srt(self, output_path: str) -> bool:
        """
        Exporte les sous-titres au format SRT
        
        Args:
            output_path: Chemin du fichier .srt de sortie
            
        Returns:
            True si succès
        """
        if not self.segments:
            print("Aucun segment à exporter")
            return False
        
        def format_time(seconds: float) -> str:
            """Convertit les secondes en format SRT (HH:MM:SS,mmm)"""
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                for seg in self.segments:
                    f.write(f"{seg.index + 1}\n")
                    f.write(f"{format_time(seg.start_time)} --> {format_time(seg.end_time)}\n")
                    f.write(f"{seg.text}\n\n")
            
            print(f"✓ SRT exporté: {output_path}")
            return True
            
        except Exception as e:
            print(f"Erreur export SRT: {e}")
            return False
    
    def export_vtt(self, output_path: str) -> bool:
        """
        Exporte les sous-titres au format WebVTT
        
        Args:
            output_path: Chemin du fichier .vtt de sortie
        """
        if not self.segments:
            return False
        
        def format_time(seconds: float) -> str:
            """Convertit les secondes en format VTT (HH:MM:SS.mmm)"""
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("WEBVTT\n\n")
                
                for seg in self.segments:
                    f.write(f"{format_time(seg.start_time)} --> {format_time(seg.end_time)}\n")
                    f.write(f"{seg.text}\n\n")
            
            print(f"✓ VTT exporté: {output_path}")
            return True
            
        except Exception as e:
            print(f"Erreur export VTT: {e}")
            return False
    
    def export_txt(self, output_path: str) -> bool:
        """
        Exporte la transcription brute en texte
        
        Args:
            output_path: Chemin du fichier .txt de sortie
        """
        if not self.segments:
            return False
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                for seg in self.segments:
                    f.write(f"[{seg.start_time:.2f}s] {seg.text}\n")
            
            print(f"✓ TXT exporté: {output_path}")
            return True
            
        except Exception as e:
            print(f"Erreur export TXT: {e}")
            return False
    
    def export_json(self, output_path: str) -> bool:
        """
        Exporte les sous-titres en JSON structuré
        
        Args:
            output_path: Chemin du fichier .json de sortie
        """
        if not self.segments:
            return False
        
        data = {
            'language': self.segments[0].language if self.segments else None,
            'duration': self.segments[-1].end_time if self.segments else 0,
            'segments': [
                {
                    'index': seg.index,
                    'start': seg.start_time,
                    'end': seg.end_time,
                    'text': seg.text
                }
                for seg in self.segments
            ]
        }
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print(f"✓ JSON exporté: {output_path}")
            return True
            
        except Exception as e:
            print(f"Erreur export JSON: {e}")
            return False
    
    def get_full_text(self) -> str:
        """Retourne tout le texte transcrit en un seul bloc"""
        return " ".join(seg.text for seg in self.segments)
    
    def reset(self):
        """Réinitialise le transcriber"""
        self.segments = []


# Exemple d'utilisation
if __name__ == "__main__":
    print("Test du module Whisper Transcription")
    
    transcriber = WhisperTranscriber(model_size="base", language="fr")
    
    # Test avec simulation (si whisper non installé)
    success = transcriber.transcribe("test_audio.wav")
    
    if success and transcriber.segments:
        print(f"\n{len(transcriber.segments)} segments transcrits:")
        for seg in transcriber.segments[:3]:  # Afficher les 3 premiers
            print(f"  [{seg.start_time:.2f}s - {seg.end_time:.2f}s] {seg.text}")
        
        # Export tests
        transcriber.export_srt("test_output.srt")
        transcriber.export_vtt("test_output.vtt")
        transcriber.export_txt("test_output.txt")
        transcriber.export_json("test_output.json")
