# 🤖 Configuration IA - Lumina Recorder

## Moteur IA Unifié

Lumina intègre un moteur IA capable de fonctionner avec **plusieurs fournisseurs**, que ce soit en local (gratuit) ou via le cloud (payant selon usage).

---

## 🏠 Option 1 : IA Locale avec Ollama (RECOMMANDÉ - Gratuit)

**Avantages :**
- ✅ 100% Gratuit et illimité
- ✅ Respect de la vie privée (tout reste sur votre PC)
- ✅ Fonctionne sans internet
- ✅ Rapide (pas de latence réseau)

### Installation d'Ollama

1. **Téléchargez Ollama** : https://ollama.com
2. **Installez-le** sur Windows
3. **Téléchargez un modèle** (dans votre terminal) :
   ```bash
   ollama pull llama3.2
   ```
   
   *Modèles recommandés :*
   - `llama3.2` (3B) - Léger et rapide, parfait pour Lumina
   - `llama3.1` (8B) - Plus intelligent, un peu plus lent
   - `mistral` (7B) - Excellent équilibre performance/taille
   - `phi3` (3.8B) - Très léger pour PCs modestes

4. **Vérifiez qu'Ollama tourne** :
   ```bash
   ollama list
   ```

### Configuration dans Lumina

Dans `config/default_config.ini` :
```ini
[ai]
provider = ollama
model = llama3.2
api_key = 
```

Ou via variables d'environnement :
```bash
set LUMINA_AI_PROVIDER=ollama
set LUMINA_AI_MODEL=llama3.2
```

---

## ☁️ Option 2 : IA Cloud (Payant à l'usage)

### OpenAI (GPT-4o, GPT-4o-mini)

**Prix :** ~$0.15 / 1M tokens (GPT-4o-mini)

```bash
set LUMINA_AI_PROVIDER=openai
set LUMINA_AI_API_KEY=sk-votre-clé-openai
set LUMINA_AI_MODEL=gpt-4o-mini
```

Obtenez votre clé : https://platform.openai.com/api-keys

---

### Anthropic Claude (Claude 3.5 Sonnet, Haiku)

**Prix :** ~$0.25 / 1M tokens (Haiku)

```bash
set LUMINA_AI_PROVIDER=claude
set LUMINA_AI_API_KEY=votre-clé-anthropic
set LUMINA_AI_MODEL=claude-3-haiku-20240307
```

Obtenez votre clé : https://console.anthropic.com

---

### Google Gemini (Gemini 1.5 Flash, Pro)

**Prix :** Gratuit jusqu'à 15 requêtes/minute, puis payant

```bash
set LUMINA_AI_PROVIDER=gemini
set LUMINA_AI_API_KEY=votre-clé-gemini
set LUMINA_AI_MODEL=gemini-1.5-flash
```

Obtenez votre clé : https://makersuite.google.com/app/apikey

---

### DeepSeek (DeepSeek-V2, DeepSeek-Coder)

**Prix :** Très compétitif, ~$0.14 / 1M tokens

```bash
set LUMINA_AI_PROVIDER=deepseek
set LUMINA_AI_API_KEY=votre-clé-deepseek
set LUMINA_AI_MODEL=deepseek-chat
```

Obtenez votre clé : https://platform.deepseek.com

---

### NVIDIA NIM (Modèles optimisés GPU)

**Prix :** Variable selon le modèle

```bash
set LUMINA_AI_PROVIDER=nvidia
set LUMINA_AI_API_KEY=votre-clé-nvidia
set LUMINA_AI_MODEL=meta/llama-3.1-8b-instruct
```

Obtenez votre clé : https://build.nvidia.com

---

## 🔧 Utilisation des Fonctionnalités IA

### Génération de sous-titres automatiques

```python
from src.services.ai_engine import get_ai_engine_from_config, LuminaAIService

# Initialisation
ai_engine = get_ai_engine_from_config('config/default_config.ini')
ai_service = LuminaAIService(ai_engine)

# Vérifier disponibilité
if ai_engine.is_available():
    # Générer sous-titres depuis une transcription
    transcript = "Bonjour à tous, aujourd'hui nous allons voir..."
    subtitles_srt = ai_service.generate_subtitles(transcript)
    print(subtitles_srt)
else:
    print("IA non disponible. Vérifiez Ollama ou votre clé API.")
```

### Détection des silences (Magic Cut)

```python
silences = ai_service.detect_silences(transcript_with_timestamps)
for silence in silences:
    print(f"Silence de {silence['duration']}s de {silence['start']} à {silence['end']}")
```

### Suggestion de miniature

```python
contexte = "Tutoriel Python : Créer une application d'enregistrement d'écran"
idea = ai_service.suggest_thumbnail(contexte)
print(idea)
# Exemple de sortie : "Fond bleu nuit, capture d'écran de code Python en gros plan, 
# titre accrocheur 'AUTOMATISEZ VOTRE BUREAU' en blanc gras, icône de caméra stylisée..."
```

### Résumé de vidéo

```python
resume = ai_service.summarize_video(transcription_complete)
print(resume)
```

### Détection d'informations sensibles (Privacy Blur)

```python
texte_ocr = "Contact: jean.dupont@email.com, Tel: 06 12 34 56 78"
infos_sensibles = ai_service.detect_sensitive_info(texte_ocr)
# Retourne: [{'type': 'email', 'value': 'jean.dupont@email.com', ...}, ...]
```

---

## 📊 Comparatif des Options

| Fournisseur | Prix | Vie Privée | Vitesse | Qualité | Recommandation |
|-------------|------|------------|---------|---------|----------------|
| **Ollama (Local)** | Gratuit | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **Usage quotidien** |
| **Gemini Flash** | Freemium | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Bon alternatif |
| **GPT-4o-mini** | Payant | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Qualité max |
| **Claude Haiku** | Payant | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Excellent |
| **DeepSeek** | Payant | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Rapport Q/P |

---

## 🎯 Recommandation pour Démarrer

1. **Installez Ollama** (gratuit)
2. **Téléchargez `llama3.2`** : `ollama pull llama3.2`
3. **Configurez Lumina** pour utiliser Ollama
4. **Testez les fonctionnalités IA** gratuitement !

Si vous avez besoin de qualité supérieure pour des cas spécifiques, basculez vers une API cloud temporairement.

---

## 🛠️ Dépannage

### "Ollama n'est pas disponible"
- Vérifiez qu'Ollama est installé : `ollama --version`
- Lancez le service : `ollama serve`
- Vérifiez les modèles : `ollama list`

### "Clé API invalide"
- Vérifiez que la clé est correcte
- Assurez-vous d'avoir du crédit sur votre compte
- Testez l'API directement via curl

### "Timeout lors de la génération"
- Pour Ollama : réduisez la taille du modèle
- Pour le Cloud : vérifiez votre connexion internet
- Augmentez le timeout dans le code si nécessaire
