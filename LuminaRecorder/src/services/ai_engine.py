"""
Lumina AI Engine - Moteur d'IA Unifié
Supporte : OpenAI, Claude, Gemini, DeepSeek, NVIDIA NIM et Ollama (Local)
"""

import os
import json
import requests
from typing import Optional, Dict, Any, List
from pathlib import Path


class LuminaAIEngine:
    """
    Moteur d'IA unifié pour Lumina Recorder.
    Permet de basculer facilement entre différents fournisseurs d'IA.
    """
    
    PROVIDERS = {
        'ollama': 'http://localhost:11434',
        'openai': 'https://api.openai.com/v1',
        'claude': 'https://api.anthropic.com/v1',
        'gemini': 'https://generativelanguage.googleapis.com/v1beta',
        'deepseek': 'https://api.deepseek.com/v1',
        'nvidia': 'https://integrate.api.nvidia.com/v1'
    }
    
    def __init__(self, provider: str = 'ollama', model: str = None, api_key: str = None):
        """
        Initialise le moteur IA.
        
        Args:
            provider: Fournisseur IA ('ollama', 'openai', 'claude', 'gemini', 'deepseek', 'nvidia')
            model: Nom du modèle à utiliser
            api_key: Clé API (non requis pour Ollama local)
        """
        self.provider = provider
        self.api_key = api_key or os.getenv(f'LUMINA_{provider.upper()}_API_KEY')
        self.base_url = self.PROVIDERS.get(provider, 'http://localhost:11434')
        
        # Modèles par défaut
        self.model = model or self._get_default_model()
        
        # Configuration spécifique
        self.headers = self._build_headers()
        
    def _get_default_model(self) -> str:
        """Retourne le modèle par défaut selon le fournisseur."""
        defaults = {
            'ollama': 'llama3.2',  # Modèle léger et rapide
            'openai': 'gpt-4o-mini',
            'claude': 'claude-3-haiku-20240307',
            'gemini': 'gemini-1.5-flash',
            'deepseek': 'deepseek-chat',
            'nvidia': 'meta/llama-3.1-8b-instruct'
        }
        return defaults.get(self.provider, 'llama3.2')
    
    def _build_headers(self) -> Dict[str, str]:
        """Construit les en-têtes HTTP selon le fournisseur."""
        headers = {'Content-Type': 'application/json'}
        
        if self.provider == 'openai' or self.provider == 'deepseek' or self.provider == 'nvidia':
            headers['Authorization'] = f'Bearer {self.api_key}'
        elif self.provider == 'claude':
            headers['x-api-key'] = self.api_key
            headers['anthropic-version'] = '2023-06-01'
        elif self.provider == 'gemini':
            # La clé API est passée dans l'URL pour Gemini
            pass
            
        return headers
    
    def generate_text(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        """
        Génère du texte à partir d'un prompt.
        
        Args:
            prompt: Le prompt utilisateur
            system_prompt: Prompt système pour guider l'IA
            **kwargs: Paramètres supplémentaires (température, max_tokens, etc.)
            
        Returns:
            La réponse générée par l'IA
        """
        if self.provider == 'ollama':
            return self._call_ollama(prompt, system_prompt, **kwargs)
        elif self.provider == 'openai' or self.provider == 'deepseek' or self.provider == 'nvidia':
            return self._call_openai_compatible(prompt, system_prompt, **kwargs)
        elif self.provider == 'claude':
            return self._call_claude(prompt, system_prompt, **kwargs)
        elif self.provider == 'gemini':
            return self._call_gemini(prompt, system_prompt, **kwargs)
        else:
            raise ValueError(f"Fournisseur IA non supporté: {self.provider}")
    
    def _call_ollama(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        """Appelle l'API Ollama locale."""
        url = f"{self.base_url}/api/generate"
        
        payload = {
            'model': self.model,
            'prompt': prompt,
            'stream': False,
            **kwargs
        }
        
        if system_prompt:
            payload['system'] = system_prompt
        
        # Un échec doit LEVER, pas être retourné comme du texte : une
        # chaîne « Erreur Ollama: … » renvoyée telle quelle finirait
        # incrustée dans une miniature ou écrite dans un fichier de
        # résumé, présentée comme une réponse du modèle.
        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                "Ollama ne répond pas. Est-il lancé (ollama serve) ?") from e
        except requests.exceptions.HTTPError as e:
            # 404 = modèle absent : le cas le plus fréquent, et le plus
            # simple à corriger si on le dit clairement
            if e.response is not None and e.response.status_code == 404:
                raise RuntimeError(
                    f"Le modèle « {self.model} » n'est pas installé. "
                    f"Installez-le avec : ollama pull {self.model}") from e
            raise RuntimeError(f"Ollama a refusé la requête : {e}") from e

        return response.json().get('response', '')
    
    def _call_openai_compatible(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        """Appelle les API compatibles OpenAI (OpenAI, DeepSeek, NVIDIA)."""
        url = f"{self.base_url}/chat/completions"
        
        messages = []
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})
        messages.append({'role': 'user', 'content': prompt})
        
        payload = {
            'model': self.model,
            'messages': messages,
            'max_tokens': kwargs.get('max_tokens', 1024),
            'temperature': kwargs.get('temperature', 0.7),
        }
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    
    def _call_claude(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        """Appelle l'API Claude d'Anthropic."""
        url = f"{self.base_url}/messages"
        
        messages = [{'role': 'user', 'content': prompt}]
        
        payload = {
            'model': self.model,
            'messages': messages,
            'max_tokens': kwargs.get('max_tokens', 1024),
        }
        
        if system_prompt:
            payload['system'] = system_prompt
        
        response = requests.post(url, headers=self.headers, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()['content'][0]['text']
    
    def _call_gemini(self, prompt: str, system_prompt: str = None, **kwargs) -> str:
        """Appelle l'API Gemini de Google."""
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        
        content = ""
        if system_prompt:
            content += f"System: {system_prompt}\n\n"
        content += f"User: {prompt}"
        
        payload = {
            'contents': [{
                'parts': [{'text': content}]
            }],
            'generationConfig': {
                'maxOutputTokens': kwargs.get('max_tokens', 1024),
                'temperature': kwargs.get('temperature', 0.7),
            }
        }
        
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()['candidates'][0]['content']['parts'][0]['text']
    
    def is_available(self) -> bool:
        """Vérifie si le service IA est disponible."""
        if self.provider == 'ollama':
            try:
                response = requests.get(f"{self.base_url}/api/tags", timeout=5)
                return response.status_code == 200
            except:
                return False
        else:
            # Pour les API cloud, on vérifie juste la présence de la clé
            return bool(self.api_key)
    
    def list_local_models(self) -> List[str]:
        """Liste les modèles disponibles localement via Ollama."""
        if self.provider != 'ollama':
            return []
        
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                models = response.json().get('models', [])
                return [m['name'] for m in models]
        except:
            pass
        return []


class LuminaAIService:
    """
    Service de haut niveau utilisant le moteur IA pour les fonctionnalités Lumina.
    """
    
    def __init__(self, ai_engine: LuminaAIEngine):
        self.ai = ai_engine
    
    def generate_subtitles(self, audio_transcript: str) -> str:
        """Génère des sous-titres formatés à partir d'une transcription."""
        system_prompt = """Tu es un assistant spécialisé dans la création de sous-titres vidéo.
        Formate le texte fourni en segments de sous-titres avec timestamps.
        Chaque segment doit faire maximum 2 lignes et durer environ 2-4 secondes.
        Retourne uniquement le format SRT."""
        
        prompt = f"""Transcription audio à convertir en sous-titres SRT:
        
        {audio_transcript}
        
        Génère le fichier SRT complet."""
        
        return self.ai.generate_text(prompt, system_prompt)
    
    def detect_silences(self, transcript_with_timestamps: str) -> List[Dict]:
        """Détecte les silences dans une transcription pour le Magic Cut."""
        system_prompt = """Analyse cette transcription avec timestamps et identifie les pauses/silences de plus de 2 secondes.
        Retourne une liste JSON d'objets avec 'start', 'end', 'duration' pour chaque silence détecté."""
        
        prompt = f"""Transcription à analyser:
        {transcript_with_timestamps}
        
        Liste des silences détectés (format JSON uniquement):"""
        
        response = self.ai.generate_text(prompt, system_prompt)
        try:
            return json.loads(response)
        except:
            return []
    
    def suggest_thumbnail(self, video_context: str) -> str:
        """Suggère une description pour une miniature attractive."""
        system_prompt = """Tu es un expert en marketing vidéo YouTube/TikTok.
        Suggère une idée de miniature accrocheuse basée sur le contenu de la vidéo.
        Décris les éléments visuels, couleurs, texte à afficher."""
        
        prompt = f"""Contexte de la vidéo: {video_context}
        
        Propose une idée de miniature virale:"""
        
        return self.ai.generate_text(prompt, system_prompt)
    
    def summarize_video(self, transcript: str) -> str:
        """Résume le contenu d'une vidéo à partir de sa transcription."""
        system_prompt = """Résume ce contenu vidéo en 3-5 points clés concis.
        Utilise un ton professionnel mais accessible."""
        
        prompt = f"""Transcription complète:
        {transcript}
        
        Résumé en points clés:"""
        
        return self.ai.generate_text(prompt, system_prompt)
    
    def detect_sensitive_info(self, text: str) -> List[Dict]:
        """Détecte les informations sensibles à flouter (emails, téléphones, cartes bancaires)."""
        system_prompt = """Analyse ce texte et identifie toutes les informations sensibles:
        - Adresses email
        - Numéros de téléphone
        - Numéros de carte bancaire
        - Adresses physiques
        - Mots de passe potentiels
        
        Retourne une liste JSON avec 'type', 'value', 'start_position', 'end_position'."""
        
        prompt = f"""Texte à analyser (OCR d'une capture d'écran):
        {text}
        
        Informations sensibles détectées (JSON uniquement):"""
        
        response = self.ai.generate_text(prompt, system_prompt)
        try:
            return json.loads(response)
        except:
            return []


# Fonction utilitaire pour initialiser l'IA depuis la config
def get_ai_engine_from_config(config_path: str = None) -> LuminaAIEngine:
    """
    Initialise le moteur IA depuis la configuration de Lumina.
    """
    # Configuration par défaut
    provider = os.getenv('LUMINA_AI_PROVIDER', 'ollama')
    model = os.getenv('LUMINA_AI_MODEL', None)
    api_key = os.getenv('LUMINA_AI_API_KEY', None)
    
    # Si un fichier de config existe, on peut le charger
    if config_path and os.path.exists(config_path):
        import configparser
        config = configparser.ConfigParser()
        config.read(config_path)
        
        if 'ai' in config:
            provider = config.get('ai', 'provider', fallback=provider)
            model = config.get('ai', 'model', fallback=model)
            api_key = config.get('ai', 'api_key', fallback=api_key)
    
    return LuminaAIEngine(provider=provider, model=model, api_key=api_key)


if __name__ == '__main__':
    # Test rapide du moteur IA
    print("🧪 Test du moteur IA Lumina...")
    
    # Test avec Ollama (local)
    print("\n1. Test Ollama (local)...")
    ollama_ai = LuminaAIEngine(provider='ollama')
    if ollama_ai.is_available():
        print(f"   ✅ Ollama disponible. Modèles: {ollama_ai.list_local_models()}")
        response = ollama_ai.generate_text("Bonjour, réponds en une phrase.", max_tokens=50)
        print(f"   Réponse: {response[:100]}...")
    else:
        print("   ⚠️ Ollama non disponible. Installez-le avec: curl -fsSL https://ollama.com/install.sh | sh")
    
    # Exemple avec une API cloud (nécessite une clé)
    # openai_ai = LuminaAIEngine(provider='openai', api_key='votre-clé')
    # if openai_ai.is_available():
    #     response = openai_ai.generate_text("Bonjour!", max_tokens=50)
    #     print(f"OpenAI: {response}")
