"""
CLI Interface - Ligne de Commande et Automation

Permet d'utiliser Lumina via :
- Commandes terminal pour scripts et batch
- API programmatique pour intégration
- Planification de tâches (cron, Task Scheduler)
- Automatisation de workflows

Commandes supportées :
- start: Démarrer un enregistrement
- stop: Arrêter l'enregistrement en cours
- status: Afficher l'état actuel
- config: Modifier la configuration
- convert: Convertir une vidéo
- transcribe: Générer des sous-titres
- trim: Découper les silences
"""

import argparse
import sys
import os
import json
from typing import Optional, Dict, Any
from pathlib import Path


class CLIInterface:
    """
    Interface en ligne de commande pour Lumina
    
    Permet l'automatisation complète via terminal
    """
    
    def __init__(self):
        self.parser = self._create_parser()
        self.recording_active = False
        self.output_dir = str(Path.home() / "Videos" / "Lumina")
    
    def _create_parser(self) -> argparse.ArgumentParser:
        """Crée le parser d'arguments"""
        parser = argparse.ArgumentParser(
            prog='lumina',
            description='Lumina Recorder - Interface CLI',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Exemples d'utilisation :
  lumina start --quality 1080p --fps 60
  lumina start --region 1920x1080+0+0 --audio-device "Microphone"
  lumina stop
  lumina convert input.mkv --output output.mp4 --preset fast
  lumina transcribe video.mp4 --language fr
  lumina trim video.mp4 --remove-silences
            """
        )
        
        subparsers = parser.add_subparsers(dest='command', help='Commandes disponibles')
        
        # Commande START
        start_parser = subparsers.add_parser('start', help='Démarrer un enregistrement')
        start_parser.add_argument('--quality', choices=['720p', '1080p', '1440p', '2160p'], 
                                 default='1080p', help='Résolution vidéo')
        start_parser.add_argument('--fps', type=int, choices=[24, 30, 60], default=30,
                                 help='Images par seconde')
        start_parser.add_argument('--bitrate', type=str, default='8000k',
                                 help='Débit vidéo (ex: 5000k, 10M)')
        start_parser.add_argument('--audio', action='store_true', default=True,
                                 help='Enregistrer l\'audio')
        start_parser.add_argument('--audio-device', type=str, default=None,
                                 help='Périphérique audio spécifique')
        start_parser.add_argument('--region', type=str, default=None,
                                 help='Région à enregistrer (WxH+X+Y)')
        start_parser.add_argument('--output', type=str, default=None,
                                 help='Dossier de sortie')
        start_parser.add_argument('--smart-focus', action='store_true',
                                 help='Activer Smart Focus')
        start_parser.add_argument('--clean-canvas', action='store_true',
                                 help='Activer Clean Canvas (masquer notifications)')
        start_parser.add_argument('--overlay', action='store_true',
                                 help='Afficher l\'overlay système')
        
        # Commande STOP
        stop_parser = subparsers.add_parser('stop', help='Arrêter l\'enregistrement')
        stop_parser.add_argument('--save', action='store_true', default=True,
                                help='Sauvegarder la vidéo')
        
        # Commande STATUS
        status_parser = subparsers.add_parser('status', help='État actuel')
        
        # Commande CONVERT
        convert_parser = subparsers.add_parser('convert', help='Convertir une vidéo')
        convert_parser.add_argument('input', type=str, help='Fichier d\'entrée')
        convert_parser.add_argument('--output', '-o', type=str, default=None,
                                   help='Fichier de sortie')
        convert_parser.add_argument('--preset', choices=['ultrafast', 'fast', 'medium', 'slow', 'veryslow'],
                                   default='medium', help='Vitesse d\'encodage')
        convert_parser.add_argument('--quality', '-q', type=int, default=23,
                                   help='Qualité CRF (18-28, plus bas = meilleur)')
        convert_parser.add_argument('--format', '-f', choices=['mp4', 'mkv', 'avi', 'mov'],
                                   default='mp4', help='Format de sortie')
        
        # Commande TRANSCRIBE
        transcribe_parser = subparsers.add_parser('transcribe', help='Transcrire audio en texte')
        transcribe_parser.add_argument('input', type=str, help='Fichier vidéo/audio')
        transcribe_parser.add_argument('--language', '-l', type=str, default='fr',
                                      help='Code langue (fr, en, es, etc.)')
        transcribe_parser.add_argument('--output', '-o', type=str, default=None,
                                      help='Fichier de sortie (.srt, .vtt, .txt)')
        transcribe_parser.add_argument('--model', choices=['tiny', 'base', 'small', 'medium', 'large'],
                                      default='base', help='Taille du modèle Whisper')
        
        # Commande TRIM
        trim_parser = subparsers.add_parser('trim', help='Découper les silences')
        trim_parser.add_argument('input', type=str, help='Fichier vidéo/audio')
        trim_parser.add_argument('--output', '-o', type=str, default=None,
                                help='Fichier de sortie')
        trim_parser.add_argument('--threshold', '-t', type=float, default=0.02,
                                help='Seuil de silence (0.0-1.0)')
        trim_parser.add_argument('--min-duration', type=float, default=0.5,
                                help='Durée minimale de silence à couper (secondes)')
        trim_parser.add_argument('--dry-run', action='store_true',
                                help='Simuler sans modifier le fichier')
        
        # Commande CONFIG
        config_parser = subparsers.add_parser('config', help='Gérer la configuration')
        config_parser.add_argument('--show', action='store_true', help='Afficher la config')
        config_parser.add_argument('--set', nargs=2, metavar=('KEY', 'VALUE'),
                                  help='Définir une valeur')
        config_parser.add_argument('--reset', action='store_true', help='Réinitialiser')
        
        return parser
    
    def run(self, args: Optional[list] = None) -> int:
        """
        Exécute la commande CLI
        
        Args:
            args: Arguments (par défaut sys.argv[1:])
            
        Returns:
            Code de retour (0 = succès)
        """
        parsed_args = self.parser.parse_args(args)
        
        if not parsed_args.command:
            self.parser.print_help()
            return 0
        
        command_method = getattr(self, f'_cmd_{parsed_args.command}', None)
        
        if command_method:
            try:
                return command_method(parsed_args)
            except KeyboardInterrupt:
                print("\n⚠ Interruption par l'utilisateur")
                return 130
            except Exception as e:
                print(f"❌ Erreur: {e}")
                return 1
        else:
            print(f"Commande inconnue: {parsed_args.command}")
            return 1
    
    def _cmd_start(self, args) -> int:
        """Commande START"""
        print("🎬 Démarrage de l'enregistrement...")
        print(f"   Qualité: {args.quality}")
        print(f"   FPS: {args.fps}")
        print(f"   Bitrate: {args.bitrate}")
        print(f"   Audio: {'Oui' if args.audio else 'Non'}")
        
        if args.region:
            print(f"   Région: {args.region}")
        
        if args.smart_focus:
            print("   ✓ Smart Focus activé")
        
        if args.clean_canvas:
            print("   ✓ Clean Canvas activé")
        
        if args.overlay:
            print("   ✓ Overlay système activé")
        
        output_path = args.output or self.output_dir
        print(f"   Sortie: {output_path}")
        
        # Simulation (dans la version réelle, appellerait le recorder_core)
        print("\n✅ Enregistrement démarré (simulation)")
        print("   Appuyez sur Ctrl+C ou lancez 'lumina stop' pour arrêter")
        
        self.recording_active = True
        return 0
    
    def _cmd_stop(self, args) -> int:
        """Commande STOP"""
        if not self.recording_active:
            print("⚠ Aucun enregistrement en cours")
            return 1
        
        print("⏹️  Arrêt de l'enregistrement...")
        
        if args.save:
            print("💾 Sauvegarde de la vidéo...")
            # Simulation
            print("✅ Vidéo sauvegardée avec succès")
        
        self.recording_active = False
        return 0
    
    def _cmd_status(self, args) -> int:
        """Commande STATUS"""
        print("📊 État de Lumina Recorder")
        print("-" * 40)
        
        if self.recording_active:
            print("Statut: 🟢 ENREGISTREMENT EN COURS")
        else:
            print("Statut: 🔴 À l'arrêt")
        
        print(f"Dossier de sortie: {self.output_dir}")
        
        # Vérifier l'espace disque
        try:
            import shutil
            total, used, free = shutil.disk_usage(self.output_dir)
            free_gb = free / (1024 ** 3)
            print(f"Espace libre: {free_gb:.1f} GB")
        except Exception:
            pass
        
        return 0
    
    def _cmd_convert(self, args) -> int:
        """Commande CONVERT"""
        print(f"🔄 Conversion de {args.input}...")
        print(f"   Format: {args.format}")
        print(f"   Preset: {args.preset}")
        print(f"   Qualité CRF: {args.quality}")
        
        output_file = args.output or f"{os.path.splitext(args.input)[0]}.{args.format}"
        print(f"   Sortie: {output_file}")
        
        # Simulation (dans la version réelle, appellerait ffmpeg)
        print("\n✅ Conversion terminée (simulation)")
        return 0
    
    def _cmd_transcribe(self, args) -> int:
        """Commande TRANSCRIBE"""
        print(f"📝 Transcription de {args.input}...")
        print(f"   Langue: {args.language}")
        print(f"   Modèle: {args.model}")
        
        output_file = args.output or f"{os.path.splitext(args.input)[0]}.srt"
        print(f"   Sortie: {output_file}")
        
        # Simulation (dans la version réelle, appellerait whisper_transcriber)
        print("\n✅ Transcription terminée (simulation)")
        return 0
    
    def _cmd_trim(self, args) -> int:
        """Commande TRIM"""
        print(f"✂️  Découpage des silences de {args.input}...")
        print(f"   Seuil: {args.threshold}")
        print(f"   Durée min: {args.min_duration}s")
        
        if args.dry_run:
            print("   Mode simulation (dry-run)")
        else:
            output_file = args.output or f"{os.path.splitext(args.input)[0]}.trimmed.mp4"
            print(f"   Sortie: {output_file}")
        
        # Simulation (dans la version réelle, appellerait magic_cut)
        print("\n✅ Découpage terminé (simulation)")
        return 0
    
    def _cmd_config(self, args) -> int:
        """Commande CONFIG"""
        if args.show:
            print("📋 Configuration actuelle")
            print("-" * 40)
            config = {
                'output_dir': self.output_dir,
                'default_quality': '1080p',
                'default_fps': 30,
                'smart_focus': False,
                'clean_canvas': True,
                'overlay': False
            }
            for key, value in config.items():
                print(f"   {key}: {value}")
        
        elif args.set:
            key, value = args.set
            print(f"✓ {key} = {value}")
            # Dans la version réelle, sauvegarderait dans le fichier de config
        
        elif args.reset:
            print("↻ Configuration réinitialisée")
        
        else:
            print("Utilisez --show, --set KEY VALUE, ou --reset")
        
        return 0


def main():
    """Point d'entrée CLI"""
    cli = CLIInterface()
    sys.exit(cli.run())


if __name__ == "__main__":
    main()
