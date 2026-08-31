"""
Lumina Recorder - Stockage des clés API des fournisseurs IA

Les clés vont dans le gestionnaire d'identifiants de Windows, jamais dans
un fichier. Le .ini ne retient que le nom du fournisseur et du modèle
choisis — rien de secret.

Pourquoi pas un fichier .env
----------------------------
Une clé en clair sur le disque est lisible par n'importe quel programme
lancé sous le même compte, se retrouve dans les sauvegardes, et finit tôt
ou tard dans un commit. Le coffre Windows la chiffre et la lie à la
session de l'utilisateur.

Les variables d'environnement restent lues en secours (LUMINA_<X>_API_KEY
puis les noms standard comme OPENAI_API_KEY) : elles servent aux
installations pilotées par un administrateur, mais Lumina n'en écrit
jamais.
"""

import os
from typing import Optional

try:
    import keyring
except ImportError:  # pragma: no cover - dépend de l'environnement
    keyring = None


SERVICE_NAME = "LuminaRecorder"

# Fournisseurs gérés, dans l'ordre où l'interface les propose. Ollama
# vient en premier : il tourne sur la machine, donc aucune donnée ne
# quitte le poste.
PROVIDERS = {
    'ollama': {
        'label': 'Ollama (local)',
        'needs_key': False,
        'local': True,
        'default_model': 'llama3.2',
        'note': "Tourne sur votre machine. Aucune donnée ne sort du poste.",
    },
    'openai': {
        'label': 'OpenAI',
        'needs_key': True,
        'local': False,
        'default_model': 'gpt-4o-mini',
        'env': ['OPENAI_API_KEY'],
        'note': "Les données envoyées transitent par les serveurs d'OpenAI.",
    },
    'claude': {
        'label': 'Claude (Anthropic)',
        'needs_key': True,
        'local': False,
        'default_model': 'claude-3-haiku-20240307',
        'env': ['ANTHROPIC_API_KEY'],
        'note': "Les données envoyées transitent par les serveurs d'Anthropic.",
    },
    'gemini': {
        'label': 'Gemini (Google)',
        'needs_key': True,
        'local': False,
        'default_model': 'gemini-1.5-flash',
        'env': ['GEMINI_API_KEY', 'GOOGLE_API_KEY'],
        'note': "Les données envoyées transitent par les serveurs de Google.",
    },
    'deepseek': {
        'label': 'DeepSeek',
        'needs_key': True,
        'local': False,
        'default_model': 'deepseek-chat',
        'env': ['DEEPSEEK_API_KEY'],
        'note': "Les données envoyées transitent par les serveurs de DeepSeek.",
    },
    'nvidia': {
        'label': 'NVIDIA NIM',
        'needs_key': True,
        'local': False,
        'default_model': 'meta/llama-3.1-8b-instruct',
        'env': ['NVIDIA_API_KEY'],
        'note': "Les données envoyées transitent par les serveurs de NVIDIA.",
    },
}


def credential_store_is_available() -> bool:
    """True si un coffre système est utilisable."""
    if keyring is None:
        return False
    try:
        backend = keyring.get_keyring()
        # keyring expose un backend « fail » quand aucun coffre réel n'est
        # disponible : y écrire lèverait à la première tentative
        return 'fail' not in type(backend).__module__.lower()
    except Exception:
        return False


def is_known_provider(provider: str) -> bool:
    return provider in PROVIDERS


def provider_needs_key(provider: str) -> bool:
    """Ollama tourne en local et ne demande aucune clé."""
    return PROVIDERS.get(provider, {}).get('needs_key', True)


def set_api_key(provider: str, api_key: str) -> bool:
    """Enregistre la clé d'un fournisseur dans le coffre système.

    Une chaîne vide supprime la clé enregistrée.

    Returns:
        True si l'opération a abouti.
    """
    if not is_known_provider(provider):
        return False
    if not credential_store_is_available():
        return False

    try:
        if not api_key:
            delete_api_key(provider)
            return True
        keyring.set_password(SERVICE_NAME, provider, api_key)
        return True
    except Exception as e:
        # Ne jamais journaliser la clé elle-même
        print(f"[Lumina] Clé « {provider} » non enregistrée : {e}")
        return False


def get_api_key(provider: str) -> Optional[str]:
    """Récupère la clé d'un fournisseur.

    Ordre de recherche : coffre système, puis LUMINA_<PROVIDER>_API_KEY,
    puis le nom standard du fournisseur (OPENAI_API_KEY...). Les
    variables d'environnement permettent un déploiement piloté par un
    administrateur sans que Lumina n'écrive quoi que ce soit.
    """
    if not is_known_provider(provider):
        return None

    if credential_store_is_available():
        try:
            stored = keyring.get_password(SERVICE_NAME, provider)
            if stored:
                return stored
        except Exception:
            pass

    candidates = [f'LUMINA_{provider.upper()}_API_KEY']
    candidates.extend(PROVIDERS[provider].get('env', []))
    for name in candidates:
        value = os.environ.get(name)
        if value:
            return value
    return None


def delete_api_key(provider: str) -> bool:
    """Supprime la clé enregistrée pour un fournisseur."""
    if not credential_store_is_available():
        return False
    try:
        keyring.delete_password(SERVICE_NAME, provider)
        return True
    except keyring.errors.PasswordDeleteError:
        # Aucune clé enregistrée : le résultat voulu est déjà atteint
        return True
    except Exception:
        return False


def has_api_key(provider: str) -> bool:
    """True si le fournisseur est utilisable en l'état."""
    if not provider_needs_key(provider):
        return True
    return bool(get_api_key(provider))


def mask_key(api_key: Optional[str]) -> str:
    """Représentation affichable d'une clé, sans la divulguer.

    L'interface doit pouvoir confirmer qu'une clé est enregistrée sans
    jamais réafficher le secret en entier.

    >>> mask_key("sk-proj-abcdefghijklmnop")
    'sk-proj-…mnop'
    """
    if not api_key:
        return ""
    if len(api_key) <= 10:
        return "…" + api_key[-2:]
    return f"{api_key[:7]}…{api_key[-4:]}"


def providers_status() -> list:
    """État de chaque fournisseur, pour l'interface.

    Ne renvoie JAMAIS les clés elles-mêmes : seulement leur présence et
    une version masquée.
    """
    status = []
    for name, info in PROVIDERS.items():
        key = get_api_key(name) if info['needs_key'] else None
        status.append({
            'id': name,
            'label': info['label'],
            'local': info['local'],
            'needs_key': info['needs_key'],
            'has_key': bool(key) if info['needs_key'] else True,
            'masked_key': mask_key(key),
            'default_model': info['default_model'],
            'note': info['note'],
        })
    return status
