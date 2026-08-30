"""
Magic Cut - Découpage Automatique des Silences

Analyse la piste audio pour :
- Détecter automatiquement les silences et pauses
- Générer des points de découpe précis
- Réduire la durée totale de la vidéo
- Conserver un flux naturel sans coupures brutales

Idéal pour :
- Tutoriels et formations
- Démos de logiciels
- Streaming enregistré
- Gain de temps au montage
"""

import numpy as np
from typing import List, Tuple, Dict
from dataclasses import dataclass
import wave
import contextlib
import os


@dataclass
class SilenceSegment:
    """Représente un segment de silence détecté"""
    start_time: float  # en secondes
    end_time: float    # en secondes
    duration: float    # durée du silence
    energy: float      # niveau d'énergie moyen pendant le silence
    should_cut: bool   # décision de découpe


@dataclass
class CutPoint:
    """Point de découpe recommandé"""
    time: float        # position en secondes
    confidence: float  # confiance de la détection (0.0 à 1.0)
    reason: str        # 'silence', 'pause_longue', 'filler_word'


class MagicCutEngine:
    """
    Moteur Magic Cut pour découpage intelligent des silences
    
    Analyse le signal audio pour identifier :
    1. Les silences complets (aucun son)
    2. Les pauses longues (> seuil configurable)
    3. Les segments à faible énergie (murmures, respirations)
    
    Propose des points de découpe optimisés pour :
    - Supprimer les temps morts
    - Garder un rythme naturel
    - Éviter les coupures dans les mots
    """
    
    def __init__(
        self,
        silence_threshold: float = 0.01,
        min_silence_duration: float = 0.5,
        max_silence_duration: float = 3.0,
        buffer_before: float = 0.1,
        buffer_after: float = 0.2
    ):
        """
        Args:
            silence_threshold: Seuil d'énergie pour considérer un silence (0.0 à 1.0)
            min_silence_duration: Durée minimale pour détecter un silence (secondes)
            max_silence_duration: Durée maximale avant de couper complètement (secondes)
            buffer_before: Marge avant le silence pour éviter de couper un mot (secondes)
            buffer_after: Marge après le silence pour transition douce (secondes)
        """
        self.silence_threshold = silence_threshold
        self.min_silence_duration = min_silence_duration
        self.max_silence_duration = max_silence_duration
        self.buffer_before = buffer_before
        self.buffer_after = buffer_after
        
        self.audio_data = None
        self.sample_rate = None
        self.duration = None
        self.silence_segments: List[SilenceSegment] = []
        self.cut_points: List[CutPoint] = []
    
    def load_audio_file(self, file_path: str) -> bool:
        """
        Charge un fichier audio pour analyse
        
        Args:
            file_path: Chemin vers le fichier audio (.wav)
            
        Returns:
            True si chargé avec succès, False sinon
        """
        if not os.path.exists(file_path):
            print(f"Fichier non trouvé: {file_path}")
            return False
        
        try:
            with contextlib.closing(wave.open(file_path, 'rb')) as wav_file:
                # Paramètres audio
                self.sample_rate = wav_file.getframerate()
                n_channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                n_frames = wav_file.getnframes()
                
                # Durée totale
                self.duration = n_frames / float(self.sample_rate)
                
                # Lecture des données
                audio_bytes = wav_file.readframes(n_frames)
                
                # Conversion en numpy array
                if sample_width == 1:
                    dtype = np.uint8
                elif sample_width == 2:
                    dtype = np.int16
                elif sample_width == 4:
                    dtype = np.int32
                else:
                    raise ValueError(f"Sample width non supporté: {sample_width}")
                
                self.audio_data = np.frombuffer(audio_bytes, dtype=dtype)
                
                # Conversion en mono si stéréo
                if n_channels == 2:
                    self.audio_data = self.audio_data.reshape(-1, 2).mean(axis=1)
                
                # Normalisation entre 0 et 1
                max_val = np.iinfo(dtype).max
                self.audio_data = self.audio_data.astype(np.float32) / max_val
                
                print(f"Audio chargé: {self.duration:.2f}s, {self.sample_rate}Hz")
                return True
                
        except Exception as e:
            print(f"Erreur lors du chargement audio: {e}")
            return False
    
    def set_audio_data(self, audio_array: np.ndarray, sample_rate: int):
        """
        Définit les données audio directement (pour traitement en temps réel)
        
        Args:
            audio_array: Tableau numpy des échantillons audio
            sample_rate: Fréquence d'échantillonnage en Hz
        """
        self.audio_data = audio_array.astype(np.float32)
        self.sample_rate = sample_rate
        self.duration = len(audio_array) / sample_rate
        
        # Normalisation
        if np.max(np.abs(self.audio_data)) > 0:
            self.audio_data = self.audio_data / np.max(np.abs(self.audio_data))
    
    def calculate_energy(self, start_sample: int, end_sample: int) -> float:
        """
        Calcule l'énergie RMS d'un segment audio
        
        Args:
            start_sample: Index de début
            end_sample: Index de fin
            
        Returns:
            Énergie RMS normalisée (0.0 à 1.0)
        """
        segment = self.audio_data[start_sample:end_sample]
        if len(segment) == 0:
            return 0.0
        
        # RMS (Root Mean Square)
        rms = np.sqrt(np.mean(segment ** 2))
        return float(rms)
    
    def detect_silences(self) -> List[SilenceSegment]:
        """
        Détecte tous les segments de silence dans l'audio
        
        Returns:
            Liste des SilenceSegment détectés
        """
        if self.audio_data is None or self.sample_rate is None:
            print("Aucune donnée audio chargée")
            return []
        
        self.silence_segments = []
        
        # Taille de fenêtre pour l'analyse (100ms)
        window_size = int(0.1 * self.sample_rate)
        step_size = int(0.05 * self.sample_rate)  # 50% de chevauchement
        
        total_samples = len(self.audio_data)
        
        # Analyse fenêtre par fenêtre
        current_silence_start = None
        current_silence_energy = []
        
        for i in range(0, total_samples - window_size, step_size):
            energy = self.calculate_energy(i, i + window_size)
            
            is_silent = energy < self.silence_threshold
            
            if is_silent:
                if current_silence_start is None:
                    # Début d'un nouveau silence
                    current_silence_start = i
                    current_silence_energy = [energy]
                else:
                    # Continuation du silence
                    current_silence_energy.append(energy)
            else:
                if current_silence_start is not None:
                    # Fin du silence
                    silence_end = i
                    
                    # Calcul de la durée
                    duration = (silence_end - current_silence_start) / self.sample_rate
                    
                    if duration >= self.min_silence_duration:
                        avg_energy = np.mean(current_silence_energy)
                        
                        self.silence_segments.append(SilenceSegment(
                            start_time=current_silence_start / self.sample_rate,
                            end_time=silence_end / self.sample_rate,
                            duration=duration,
                            energy=avg_energy,
                            should_cut=duration <= self.max_silence_duration
                        ))
                    
                    current_silence_start = None
                    current_silence_energy = []
        
        # Gérer le dernier silence s'il existe
        if current_silence_start is not None:
            duration = (total_samples - current_silence_start) / self.sample_rate
            if duration >= self.min_silence_duration:
                avg_energy = np.mean(current_silence_energy) if current_silence_energy else 0
                self.silence_segments.append(SilenceSegment(
                    start_time=current_silence_start / self.sample_rate,
                    end_time=total_samples / self.sample_rate,
                    duration=duration,
                    energy=avg_energy,
                    should_cut=duration <= self.max_silence_duration
                ))
        
        print(f"{len(self.silence_segments)} segments de silence détectés")
        return self.silence_segments
    
    def generate_cut_points(self) -> List[CutPoint]:
        """
        Génère les points de découpe optimaux basés sur les silences
        
        Returns:
            Liste triée des CutPoint recommandés
        """
        if not self.silence_segments:
            self.detect_silences()
        
        self.cut_points = []
        
        for segment in self.silence_segments:
            if not segment.should_cut:
                # Silence trop long, on ne coupe pas complètement
                # On propose juste un point au milieu pour révision manuelle
                mid_point = segment.start_time + segment.duration / 2
                self.cut_points.append(CutPoint(
                    time=mid_point,
                    confidence=0.5,
                    reason='pause_longue'
                ))
            else:
                # Silence court, on peut couper
                # Point de coupe : début du silence + buffer
                cut_time = segment.start_time - self.buffer_before
                
                if cut_time > 0:
                    self.cut_points.append(CutPoint(
                        time=cut_time,
                        confidence=0.9,
                        reason='silence'
                    ))
        
        # Trier par temps
        self.cut_points.sort(key=lambda p: p.time)
        
        # Fusionner les points trop proches (< 0.5s)
        merged_points = []
        for point in self.cut_points:
            if not merged_points:
                merged_points.append(point)
            else:
                last_point = merged_points[-1]
                if point.time - last_point.time < 0.5:
                    # Garder le point avec la plus haute confiance
                    if point.confidence > last_point.confidence:
                        merged_points[-1] = point
                else:
                    merged_points.append(point)
        
        self.cut_points = merged_points
        
        print(f"{len(self.cut_points)} points de découpe générés")
        return self.cut_points
    
    def get_trimmed_segments(self) -> List[Tuple[float, float]]:
        """
        Retourne les segments à conserver après découpage
        
        Returns:
            Liste de tuples (start_time, end_time) des segments à garder
        """
        if not self.cut_points:
            self.generate_cut_points()
        
        if not self.cut_points:
            # Aucun point de coupe, garder tout
            return [(0.0, self.duration)]
        
        segments = []
        current_start = 0.0
        
        for i, point in enumerate(self.cut_points):
            # Segment de current_start à point.time + buffer_after
            segment_end = point.time + self.buffer_after
            segment_end = min(segment_end, self.duration)
            
            if segment_end > current_start + 0.5:  # Segment minimum de 0.5s
                segments.append((current_start, segment_end))
            
            # Nouveau départ après le silence
            current_start = point.time + self.buffer_after
        
        # Dernier segment jusqu'à la fin
        if current_start < self.duration - 0.5:
            segments.append((current_start, self.duration))
        
        return segments
    
    def estimate_time_saved(self) -> float:
        """
        Estime le temps gagné après découpage
        
        Returns:
            Temps économisé en secondes
        """
        if not self.silence_segments:
            return 0.0
        
        total_silence_to_cut = sum(
            s.duration for s in self.silence_segments if s.should_cut
        )
        
        return total_silence_to_cut
    
    def export_edl(self, output_path: str):
        """
        Exporte une Edit Decision List (EDL) pour montage
        
        Args:
            output_path: Chemin du fichier EDL de sortie
        """
        segments = self.get_trimmed_segments()
        
        with open(output_path, 'w') as f:
            f.write("# Lumina Magic Cut - EDL\n")
            f.write(f"# Source Duration: {self.duration:.2f}s\n")
            f.write(f"# Estimated Output: {sum(e-s for s,e in segments):.2f}s\n")
            f.write(f"# Time Saved: {self.estimate_time_saved():.2f}s\n")
            f.write("#\n")
            f.write("# Format: START END\n")
            f.write("#\n")
            
            for i, (start, end) in enumerate(segments):
                f.write(f"{i+1:03d}: {start:08.3f} {end:08.3f}\n")
        
        print(f"EDL exportée: {output_path}")
    
    def reset(self):
        """Réinitialise le moteur"""
        self.audio_data = None
        self.sample_rate = None
        self.duration = None
        self.silence_segments = []
        self.cut_points = []


# Exemple d'utilisation
if __name__ == "__main__":
    print("Test du module Magic Cut")
    engine = MagicCutEngine(
        silence_threshold=0.02,
        min_silence_duration=0.5,
        max_silence_duration=2.0
    )
    
    # Créer un audio test synthétique
    sample_rate = 44100
    duration = 10.0  # secondes
    
    # Générer un signal avec des silences
    t = np.linspace(0, duration, int(sample_rate * duration))
    audio = np.sin(2 * np.pi * 440 * t)  # La à 440Hz
    
    # Ajouter des silences
    audio[int(sample_rate * 2):int(sample_rate * 3)] = 0  # Silence 1s à 2s
    audio[int(sample_rate * 5):int(sample_rate * 6)] = 0  # Silence 1s à 5s
    audio[int(sample_rate * 7.5):int(sample_rate * 8.5)] = 0  # Silence 1s à 7.5s
    
    engine.set_audio_data(audio, sample_rate)
    
    silences = engine.detect_silences()
    print(f"\nSilences détectés: {len(silences)}")
    for s in silences:
        print(f"  - {s.start_time:.2f}s à {s.end_time:.2f}s ({s.duration:.2f}s)")
    
    cuts = engine.generate_cut_points()
    print(f"\nPoints de coupe: {len(cuts)}")
    for c in cuts:
        print(f"  - {c.time:.2f}s (confiance: {c.confidence:.2f}, raison: {c.reason})")
    
    time_saved = engine.estimate_time_saved()
    print(f"\nTemps estimé économisé: {time_saved:.2f}s")
    
    segments = engine.get_trimmed_segments()
    print(f"\nSegments à conserver: {len(segments)}")
    for i, (s, e) in enumerate(segments):
        print(f"  Segment {i+1}: {s:.2f}s → {e:.2f}s ({e-s:.2f}s)")
