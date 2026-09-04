"""
Lumina Recorder - Video Encoder Module
Utilise FFmpeg pour encoder les fichiers bruts en vidéo finale optimisée.
"""

import subprocess
import os
from pathlib import Path
from typing import Optional, Tuple


class VideoEncoder:
    """
    Encodeur vidéo basé sur FFmpeg pour Lumina.
    Gère la fusion audio/vidéo, la compression et l'optimisation du bitrate.
    """
    
    def __init__(self, output_format: str = "mp4", codec: str = "libx264"):
        self.output_format = output_format
        self.codec = codec
        self.ffmpeg_path = self._find_ffmpeg()
        
    def _find_ffmpeg(self) -> str:
        """Recherche l'exécutable FFmpeg dans le PATH"""
        try:
            result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
            if result.returncode == 0:
                return 'ffmpeg'
        except FileNotFoundError:
            pass
        
        # Chemins Windows courants si FFmpeg n'est pas dans le PATH
        possible_paths = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe")
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
                
        raise FileNotFoundError(
            "FFmpeg non trouvé. Veuillez l'installer et l'ajouter au PATH.\n"
            "Téléchargement: https://www.gyan.dev/ffmpeg/builds/"
        )
    
    def encode(self, video_path: str, audio_path: Optional[str], 
               output_path: str, resolution: str, fps: int, 
               bitrate: str = "5000k", audio_gain: float = 0.5,
               encoder_preset: str = "medium",
               system_audio_path: Optional[str] = None) -> bool:
        """
        Encode la vidéo finale avec FFmpeg.

        Args:
            video_path: Chemin vers la vidéo brute
            audio_path: Chemin vers l'audio brut (optionnel)
            output_path: Chemin de sortie final
            resolution: Résolution cible (ex: 1920x1080)
            fps: Frames par seconde
            bitrate: Bitrate vidéo (ex: 5000k)
            audio_gain: Gain audio (0.1 à 2.0)
            encoder_preset: Vitesse de compression (ultrafast, fast, medium, slow, veryslow)
            system_audio_path: Son système capté en loopback (optionnel).
                Mixé avec le micro par le filtre amix ; FFmpeg gère le
                rééchantillonnage entre 44,1 kHz (micro) et 48 kHz (loopback).

        Returns:
            True si succès, False sinon
        """
        if not os.path.exists(video_path):
            print(f"[Lumina] Fichier vidéo introuvable: {video_path}")
            return False
            
        width, height = resolution.split('x')

        # Le flux brut du recorder est un MJPEG nu à cadence constante,
        # sans en-tête : FFmpeg doit savoir qu'il s'agit de ce format et
        # à quelle cadence le lire. Sans -framerate il serait lu à
        # 25 im/s et la vidéo dériverait par rapport au son. Les autres
        # conteneurs (AVI, MP4) gardent la lecture historique.
        if video_path.lower().endswith('.mjpeg'):
            entree = ['-f', 'mjpeg', '-framerate', str(fps), '-i', video_path]
        else:
            entree = ['-r', str(fps), '-i', video_path]

        # Construction de la commande FFmpeg
        cmd = [
            self.ffmpeg_path,
            '-y',  # Écraser la sortie si existe
            *entree,
        ]
        
        has_mic = bool(audio_path and os.path.exists(audio_path))
        has_system = bool(system_audio_path
                          and os.path.exists(system_audio_path))

        # Micro + son système : mixage par FFmpeg
        if has_mic and has_system:
            cmd.extend([
                '-i', audio_path,
                '-i', system_audio_path,
                '-c:v', self.codec,
                '-preset', encoder_preset,
                '-b:v', bitrate,
                '-vf', f'scale={width}:{height}',
                # duration=longest : ne pas tronquer si une source s'arrête
                # avant l'autre (le loopback ne délivre rien dans le silence)
                # amix divise CHAQUE entrée par le nombre d'entrées :
                # sans normalize=0, le micro sortait à -6 dB, inaudible
                # sous la bande-son d'une vidéo.
                #
                # Mesuré sur un enregistrement réel : la bande vocale
                # (300-3400 Hz) sortait 2,3 dB SOUS le reste — la voix
                # était couverte. La voix est le propos d'un
                # enregistrement commenté : elle est donc remontée
                # (+3,5 dB) et le son système nettement reculé (35 %,
                # soit -9 dB), ce qui laisse ~12 dB d'écart en faveur de
                # la voix — la marge habituelle d'un commentaire
                # audible sur fond musical.
                #
                # dynaudnorm sur la voix égalise les écarts de distance
                # au micro sans écraser la dynamique (f=250 ms, g=5) :
                # une phrase prononcée en s'éloignant reste audible.
                # alimiter en sortie empêche la somme des deux sources
                # de saturer.
                '-filter_complex',
                f'[1:a]volume={audio_gain * 1.5},'
                f'dynaudnorm=f=250:g=5:p=0.9[mic];'
                f'[2:a]volume={audio_gain * 0.35}[sys];'
                f'[mic][sys]amix=inputs=2:duration=longest'
                f':normalize=0:dropout_transition=0,'
                f'alimiter=limit=0.95[aout]',
                '-map', '0:v',
                '-map', '[aout]',
                '-c:a', 'aac',
                '-b:a', '192k',
            ])
        # Son système seul (micro coupé)
        elif has_system:
            cmd.extend([
                '-i', system_audio_path,
                '-c:v', self.codec,
                '-preset', encoder_preset,
                '-b:v', bitrate,
                '-vf', f'scale={width}:{height}',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-filter:a', f'volume={audio_gain}',
            ])
        elif has_mic:
            cmd.extend([
                '-i', audio_path,
                '-c:v', self.codec,
                '-preset', encoder_preset,
                '-b:v', bitrate,
                '-vf', f'scale={width}:{height}',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-filter:a', f'volume={audio_gain}',
                '-shortest'
            ])
        else:
            cmd.extend([
                '-c:v', self.codec,
                '-preset', encoder_preset,
                '-b:v', bitrate,
                '-vf', f'scale={width}:{height}',
                '-an'  # Pas d'audio
            ])
            
        cmd.append(output_path)
        
        print(f"[Lumina] Encodage en cours... ({resolution}, {bitrate})")
        print(f"Commande: {' '.join(cmd)}")
        
        try:
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # Timeout 1 heure pour vidéos longues
            )
            
            if process.returncode == 0:
                print(f"[Lumina] Encodage terminé avec succès: {output_path}")
                
                # Nettoyage des fichiers temporaires
                self._cleanup_temp_files(video_path, audio_path,
                                         system_audio_path)
                
                return True
            else:
                print(f"[Lumina] Erreur d'encodage: {process.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print("[Lumina] Erreur: Temps d'encodage dépassé")
            return False
        except Exception as e:
            print(f"[Lumina] Erreur exceptionnelle: {e}")
            return False
    
    def _cleanup_temp_files(self, *paths):
        """Supprime les fichiers temporaires"""
        for path in paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"[Lumina] Fichier temporaire supprimé: {path}")
                except Exception as e:
                    print(f"[Lumina] Impossible de supprimer {path}: {e}")
    
    def get_supported_encoders(self) -> list:
        """Retourne la liste des encodeurs supportés par FFmpeg"""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, '-encoders'],
                capture_output=True, text=True
            )
            encoders = []
            for line in result.stdout.split('\n'):
                if 'V.....' in line or 'VA....' in line:  # Codeurs vidéo
                    parts = line.split()
                    if len(parts) > 1:
                        encoders.append(parts[1])
            return encoders
        except Exception:
            return ['libx264', 'libx265', 'mpeg4']


if __name__ == "__main__":
    # Test rapide
    try:
        encoder = VideoEncoder()
        print("FFmpeg trouvé:", encoder.ffmpeg_path)
        print("Encodeurs supportés:", encoder.get_supported_encoders()[:10])
    except Exception as e:
        print("Erreur:", e)
