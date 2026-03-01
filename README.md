# CRon 🎙️
> Génère automatiquement tes comptes rendus de réunion.

Enregistre la réunion (micro ou son système) → transcrit avec Whisper local → génère le CR formaté avec le LLM de ton choix → ajoute en haut du fichier de suivi.

---

## Installation

```bash
# Minimum pour fonctionner (Mistral + Whisper local)
pip install requests sounddevice numpy openai-whisper torch

# Ou tout d'un coup
pip install -r requirements.txt
```

> **Note torch :** pour une install CPU uniquement (plus légère) :
> `pip install torch --index-url https://download.pytorch.org/whl/cpu`

---

## Premier lancement

```bash
python main.py
```

Si aucune config n'est détectée, un **wizard interactif** se lance automatiquement : provider LLM, clé API, source audio, modèle Whisper, fichier de suivi. Ça prend 2 minutes.

---

## Providers LLM supportés

| Provider   | Modèle par défaut      | Clé API                        |
|------------|------------------------|--------------------------------|
| Mistral    | `mistral-large-latest` | console.mistral.ai             |
| OpenAI     | `gpt-4o`               | platform.openai.com/api-keys   |
| Anthropic  | `claude-sonnet-4-6`    | console.anthropic.com          |
| Google     | `gemini-1.5-pro`       | aistudio.google.com/app/apikey |

Mistral est le provider par défaut. Pas de SDK supplémentaire — `requests` suffit.

---

## Utilisation

### Lancement standard (mode interactif)
```bash
python main.py
```
L'appli propose : micro / son système / les deux / charger un fichier.  
Appuie sur **Entrée** pour stopper l'enregistrement.

### Raccourcis en ligne de commande
```bash
python main.py -f réunion.mp3        # depuis un fichier audio directement
python main.py -s system             # forcer le son système pour cette session
python main.py -s both               # forcer micro + son système
python main.py -y                    # mode non-interactif (zéro confirmations)
python main.py -t transcription.txt  # skip Whisper, utilise un fichier texte
```

### Autres commandes
```bash
python main.py config                      # modifier la configuration
python main.py devices                     # lister les devices audio disponibles
python main.py transcribe -f audio.mp3     # transcription seule
python main.py generate -f notes.txt       # générer un CR depuis un fichier texte
```

---

## Réunions en ligne (Teams, Zoom, Meet...)

Pour capturer le son de l'ordi (interlocuteurs en ligne), il faut configurer le **monitor** PulseAudio/PipeWire.

**Étape 1 — trouver le bon device :**
```bash
python main.py devices
```
Les devices marqués 🖥 sont les monitors (son système). Note l'index, ex : `8`.

**Étape 2 — configurer :**
```bash
python main.py config
# → Source audio par défaut : both (ou system)
# → Index device son système : 8
```

En mode `both`, micro et son système sont enregistrés en parallèle et mixés à 50/50.

---

## Workflow complet

1. `python main.py` au début de la réunion
2. Choix de la source audio dans le menu
3. Enregistrement — appuie sur **Entrée** pour stopper
4. La transcription s'affiche → option de l'éditer dans `$EDITOR`
5. Le CR généré s'affiche → option de l'éditer
6. Confirmation → ajouté **en haut** du fichier de suivi `.md`

---

## Format de sortie

```
Date : 19/02/26
Participants :
NOM, Prénom, Rôle

Minutes :
Résumé chronologique des points abordés
Décisions prises et éléments ayant motivé ces décisions

Actions :
@Personne :
  Nom de la tâche :
    Jeudi - 20/02/2026 => description de l'action
```

Chaque nouveau CR est inséré **en haut** du fichier de suivi, les anciens restent en dessous.

---

## Configuration

Stockée dans `config.json` à côté de `main.py`.  
Modifiable à tout moment avec `python main.py config`.

**Modèles Whisper :**

| Modèle   | Vitesse | Précision    |
|----------|---------|--------------|
| `tiny`   | ⚡⚡⚡⚡ | ★☆☆☆☆      |
| `base`   | ⚡⚡⚡   | ★★☆☆☆  ← recommandé |
| `small`  | ⚡⚡     | ★★★☆☆      |
| `medium` | ⚡       | ★★★★☆      |
| `large`  | 🐢       | ★★★★★      |
