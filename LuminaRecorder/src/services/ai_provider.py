"""
Lumina Recorder - Sélection du fournisseur IA et tâches associées

Construit un moteur IA à partir de la configuration et du coffre système,
et expose les trois usages retenus :

- un titre court pour les miniatures
- un résumé de l'enregistrement, avec chapitres
- la correction des sous-titres produits par Whisper

Confidentialité
---------------
Deux de ces usages envoient le CONTENU PARLÉ de l'enregistrement au
fournisseur choisi. Sur un service distant, cela signifie transmettre à
un tiers tout ce qui a été dit devant le micro. Ollama traite la demande
sur la machine et ne transmet rien.

`sends_data_offsite()` permet à l'interface de le signaler avant que
l'utilisateur ne coche l'option. Aucune de ces tâches ne s'exécute sans
que l'option correspondante ait été activée explicitement.
"""

import re
from typing import List, Optional

from services.ai_credentials import (PROVIDERS, get_api_key, has_api_key,
                                     is_known_provider)
from services.ai_engine import LuminaAIEngine


DEFAULT_PROVIDER = 'ollama'

# Au-delà, on tronque : une transcription d'une heure dépasserait la
# fenêtre de contexte des petits modèles et coûterait cher sur les
# services facturés au jeton
MAX_TRANSCRIPT_CHARS = 12000


def sends_data_offsite(provider: str) -> bool:
    """True si ce fournisseur transmet les données hors de la machine."""
    info = PROVIDERS.get(provider)
    if info is None:
        return True     # inconnu : on suppose le pire
    return not info['local']


def build_engine(provider: str,
                 model: Optional[str] = None) -> Optional[LuminaAIEngine]:
    """Construit un moteur pour ce fournisseur, ou None s'il est
    inutilisable (fournisseur inconnu, clé manquante).

    Renvoyer None plutôt qu'un moteur muet est délibéré : une
    fonctionnalité IA sans moteur doit être visiblement indisponible, pas
    silencieusement inerte.
    """
    if not is_known_provider(provider):
        return None
    if not has_api_key(provider):
        return None

    return LuminaAIEngine(
        provider=provider,
        model=model or PROVIDERS[provider]['default_model'],
        api_key=get_api_key(provider),
    )


def build_engine_from_config(config) -> Optional[LuminaAIEngine]:
    """Construit le moteur depuis la configuration de Lumina.

    Le .ini ne contient que le nom du fournisseur et du modèle : la clé
    vient du coffre système (voir ai_credentials).
    """
    provider = config.get('ai', 'provider', fallback=DEFAULT_PROVIDER)
    model = config.get('ai', 'model', fallback=None)
    return build_engine(provider, model or None)


def _strip_line_prefix(text: str) -> str:
    """Retire un préfixe « Ligne 3 : » ajouté par le modèle.

    Constaté en test réel avec qwen2.5 : malgré une numérotation déjà
    demandée, le modèle réécrit « 1. Ligne 1 : bonjour ». Sans ce
    nettoyage, « Ligne 1 : » serait incrusté dans les sous-titres.
    """
    return re.sub(r'^\s*(ligne|line)\s*\d*\s*[:\-]\s*', '', text,
                  flags=re.IGNORECASE).strip()


def _truncate(text: str, limit: int = MAX_TRANSCRIPT_CHARS) -> str:
    """Tronque une transcription trop longue en le signalant."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[…transcription tronquée]"


class AITasks:
    """Les trois usages IA de Lumina.

    Chaque méthode renvoie une valeur vide en cas d'échec plutôt que de
    lever : une IA défaillante ne doit jamais faire perdre un
    enregistrement déjà capturé.
    """

    def __init__(self, engine: LuminaAIEngine):
        self.engine = engine

    # -- Titre de miniature ------------------------------------------

    def thumbnail_title(self, context: str) -> str:
        """Titre court à incruster sur les miniatures (6 mots maximum).

        Le générateur de miniatures attend un texte à afficher, pas une
        description de maquette : la consigne l'impose explicitement.
        """
        system = ("Tu écris des titres courts pour des miniatures de "
                  "vidéo. Réponds UNIQUEMENT par le titre, en français, "
                  "six mots maximum, sans guillemets ni ponctuation "
                  "finale, sans explication.")
        try:
            answer = self.engine.generate_text(
                f"Sujet de la vidéo : {context}\n\nTitre :", system)
        except Exception as e:
            print(f"[Lumina] Titre de miniature indisponible : {e}")
            return ""

        return self._clean_title(answer)

    @staticmethod
    def _clean_title(answer: str) -> str:
        """Garde la première ligne utile, sans guillemets, six mots max.

        Les modèles ajoutent volontiers « Voici un titre : » ou des
        guillemets malgré la consigne.
        """
        if not answer:
            return ""
        line = next((l.strip() for l in answer.strip().splitlines()
                     if l.strip()), "")
        # Les modèles préfixent volontiers leur réponse (« Voici le
        # titre : », « Réponse : ») malgré la consigne. On coupe à partir
        # du dernier deux-points d'un préfixe court, jamais dans un titre
        # qui contiendrait lui-même un deux-points.
        prefix = re.match(r'^[^:]{0,40}:\s*', line)
        if prefix and re.search(r'\b(voici|titre|r[ée]ponse|suggestion)\b',
                                prefix.group(0), re.IGNORECASE):
            line = line[prefix.end():]
        # Guillemets et ponctuation finale s'imbriquent (« "Titre". ») :
        # un seul passage en laisserait toujours un des deux
        line = line.strip()
        for _ in range(3):
            nettoye = line.strip('"\'«»  ').rstrip('.!?').strip()
            if nettoye == line:
                break
            line = nettoye
        return " ".join(line.split()[:6])

    # -- Résumé ------------------------------------------------------

    def summary(self, transcript: str) -> str:
        """Résumé de l'enregistrement à partir de sa transcription.

        ATTENTION : envoie le contenu parlé au fournisseur configuré.
        """
        if not transcript.strip():
            return ""
        system = ("Tu résumes des enregistrements d'écran. Donne un "
                  "résumé en 3 à 5 points, en français, puis une ligne "
                  "« Mots-clés : » avec cinq termes séparés par des "
                  "virgules. Pas d'introduction.")
        try:
            return self.engine.generate_text(
                f"Transcription :\n{_truncate(transcript)}\n\nRésumé :",
                system).strip()
        except Exception as e:
            print(f"[Lumina] Résumé indisponible : {e}")
            return ""

    # -- Correction des sous-titres ----------------------------------

    def fix_subtitles(self, lines: List[str]) -> List[str]:
        """Corrige ponctuation, noms propres et termes techniques.

        Whisper transcrit phonétiquement le jargon (« pi torche » pour
        « PyTorch »). Le modèle ne doit RIEN reformuler d'autre : le
        texte reste calé sur des horodatages, une ligne fusionnée ou
        supprimée désynchroniserait tout le fichier.

        Renvoie la liste d'origine si la correction échoue ou si le
        nombre de lignes ne correspond plus.
        """
        if not lines:
            return lines

        system = ("Tu corriges une transcription automatique. Corrige "
                  "UNIQUEMENT l'orthographe, la ponctuation, les noms "
                  "propres et les termes techniques mal transcrits. "
                  "Ne reformule pas, ne résume pas, ne fusionne pas. "
                  "Réponds avec EXACTEMENT le même nombre de lignes, "
                  "numérotées comme à l'entrée.")
        numbered = "\n".join(f"{i + 1}. {line}"
                             for i, line in enumerate(lines))
        try:
            answer = self.engine.generate_text(
                f"Lignes à corriger :\n{_truncate(numbered)}\n\n"
                f"Lignes corrigées :", system)
        except Exception as e:
            print(f"[Lumina] Correction des sous-titres indisponible : {e}")
            return lines

        corrected = self._parse_numbered(answer, len(lines))
        # Un décalage du nombre de lignes désynchroniserait les
        # horodatages : mieux vaut la transcription brute que des
        # sous-titres décalés
        if corrected is None:
            print("[Lumina] Correction ignorée : le nombre de lignes "
                  "renvoyé ne correspond pas")
            return lines
        return corrected

    @staticmethod
    def _parse_numbered(answer: str, expected: int) -> Optional[List[str]]:
        """Extrait les lignes numérotées, ou None si le compte diffère."""
        if not answer:
            return None
        found = {}
        for raw in answer.strip().splitlines():
            match = re.match(r'\s*(\d+)\s*[.)]\s*(.*)', raw)
            if match:
                index = int(match.group(1)) - 1
                if 0 <= index < expected:
                    found[index] = _strip_line_prefix(match.group(2))
        if len(found) != expected:
            return None
        return [found[i] for i in range(expected)]
