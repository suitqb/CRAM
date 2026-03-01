#!/usr/bin/env python3
"""
CRon — Générateur de compte rendu de réunion — CLI
Stack : Whisper local (transcription) + LLM au choix (génération)
"""

import os
import sys
import json
import tempfile
import threading
import time
import wave
import argparse
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
CONFIG_FILE = Path(__file__).parent / "config.json"
DEFAULT_CONFIG = {
    "llm_provider":      "mistral",
    "mistral_api_key":   "",
    "mistral_model":     "mistral-large-latest",
    "openai_api_key":    "",
    "openai_model":      "gpt-4o",
    "anthropic_api_key": "",
    "anthropic_model":   "claude-sonnet-4-6",
    "google_api_key":    "",
    "google_model":      "gemini-1.5-pro",
    "audio_source":      "mic",
    "mic_device":        None,
    "system_device":     None,
    "whisper_mode":      "local",
    "whisper_model":     "base",
    "output_file":       str(Path(__file__).parent / "compte_rendus.md"),
    "samplerate":        44100,
}

# ─────────────────────────────────────────────
# COULEURS & UI
# ─────────────────────────────────────────────
R   = "\033[31m"
G   = "\033[32m"
Y   = "\033[33m"
B   = "\033[34m"
M   = "\033[35m"
C   = "\033[36m"
BO  = "\033[1m"
DIM = "\033[2m"
RST = "\033[0m"

def info(msg):   print(f"  {B}ℹ{RST}  {msg}")
def ok(msg):     print(f"  {G}✓{RST}  {msg}")
def warn(msg):   print(f"  {Y}⚠{RST}  {msg}")
def err(msg):    print(f"  {R}✗{RST}  {msg}", file=sys.stderr)
def step(msg):   print(f"\n  {BO}{M}→{RST}  {BO}{msg}{RST}")

def title(msg):
    w = max(len(msg) + 4, 40)
    print(f"\n{BO}{C}┌{'─' * (w)}┐{RST}")
    print(f"{BO}{C}│  {msg:<{w-2}}│{RST}")
    print(f"{BO}{C}└{'─' * (w)}┘{RST}\n")

def banner():
    print(f"""
{BO}{C}  ╔═══════════════════════════════════╗
  ║   🎙️  CRon — Compte Rendu Auto     ║
  ╚═══════════════════════════════════╝{RST}""")

def separator():
    print(f"  {DIM}{'─' * 45}{RST}")

def ask(prompt, default=None):
    """Input avec valeur par défaut affichée."""
    hint = f" {DIM}[{default}]{RST}" if default is not None else ""
    val = input(f"  {Y}?{RST}  {prompt}{hint} : ").strip()
    return val if val else (default or "")

def ask_yn(prompt, default="n"):
    """Oui/Non avec défaut."""
    hint = "O/n" if default == "o" else "o/N"
    val = input(f"\n  {Y}?{RST}  {prompt} {DIM}[{hint}]{RST} : ").strip().lower()
    if val == "":
        return default == "o"
    return val in ("o", "oui", "y", "yes")

def choose(prompt, options, default=None):
    """
    Menu numéroté. options = liste de (label, description) ou liste de strings.
    Retourne l'index choisi.
    """
    print(f"\n  {BO}{prompt}{RST}")
    separator()
    for i, opt in enumerate(options):
        label = opt[0] if isinstance(opt, tuple) else opt
        desc  = f"  {DIM}{opt[1]}{RST}" if isinstance(opt, tuple) else ""
        marker = f"{G}▶{RST}" if default == i else " "
        print(f"  {marker} {BO}{i+1}{RST}. {label}{desc}")
    separator()

    while True:
        hint = f" {DIM}[{default+1}]{RST}" if default is not None else ""
        val = input(f"  {Y}?{RST}  Choix{hint} : ").strip()
        if val == "" and default is not None:
            return default
        if val.isdigit() and 1 <= int(val) <= len(options):
            return int(val) - 1
        warn(f"Entre un nombre entre 1 et {len(options)}")

# ─────────────────────────────────────────────
# SPINNER
# ─────────────────────────────────────────────
class Spinner:
    FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

    def __init__(self, msg):
        self.msg = msg
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._spin, daemon=True)

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            print(f"\r  {C}{self.FRAMES[i % len(self.FRAMES)]}{RST}  {self.msg}...", end="", flush=True)
            i += 1
            time.sleep(0.08)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._t.join()
        print(f"\r  {G}✓{RST}  {self.msg} — terminé{' ' * 10}")

# ─────────────────────────────────────────────
# CONFIG HELPERS
# ─────────────────────────────────────────────
def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return None   # Pas de config = première fois

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    ok(f"Config sauvegardée dans {CONFIG_FILE}")

def get_api_key_for_provider(cfg, provider):
    keys = {
        "mistral":   cfg.get("mistral_api_key"),
        "openai":    cfg.get("openai_api_key"),
        "anthropic": cfg.get("anthropic_api_key"),
        "google":    cfg.get("google_api_key"),
    }
    return keys.get(provider, "")

def config_is_valid(cfg):
    """Vérifie que la config a le minimum pour fonctionner."""
    if not cfg:
        return False
    provider = cfg.get("llm_provider", "")
    return bool(get_api_key_for_provider(cfg, provider))

# ─────────────────────────────────────────────
# WIZARD PREMIER LANCEMENT
# ─────────────────────────────────────────────
def run_setup_wizard():
    """Wizard interactif pour la première configuration."""
    title("🚀  Premier lancement — Configuration initiale")
    print("  Bienvenue dans CRon ! On va configurer l'appli ensemble.")
    print("  Ça prend 2 minutes et c'est fait une seule fois.\n")

    cfg = DEFAULT_CONFIG.copy()

    # 1. Provider LLM
    step("Quel service d'IA veux-tu utiliser pour générer les comptes rendus ?")
    providers = [
        ("Mistral",   "mistral-large-latest — recommandé, gratuit au démarrage"),
        ("OpenAI",    "GPT-4o"),
        ("Anthropic", "Claude"),
        ("Google",    "Gemini"),
    ]
    idx = choose("Provider LLM", providers, default=0)
    provider_keys = ["mistral", "openai", "anthropic", "google"]
    cfg["llm_provider"] = provider_keys[idx]

    # 2. Clé API
    provider_name = providers[idx][0]
    urls = {
        "mistral":   "https://console.mistral.ai",
        "openai":    "https://platform.openai.com/api-keys",
        "anthropic": "https://console.anthropic.com",
        "google":    "https://aistudio.google.com/app/apikey",
    }
    key_field = f"{cfg['llm_provider']}_api_key"
    print(f"\n  Récupère ta clé API sur : {BO}{urls[cfg['llm_provider']]}{RST}")
    while True:
        key = ask(f"Clé API {provider_name}")
        if key:
            cfg[key_field] = key
            break
        warn("La clé API est obligatoire pour continuer.")

    # 3. Source audio
    step("Comment se passe généralement tes réunions ?")
    sources = [
        ("Micro uniquement",          "réunions en présentiel dans la même salle"),
        ("Son système uniquement",    "réunion en ligne (Teams, Zoom, Meet...) — tu n'as pas besoin de parler"),
        ("Micro + son système mixés", "réunion en ligne où tu parles aussi"),
    ]
    idx = choose("Source audio par défaut", sources, default=0)
    source_keys = ["mic", "system", "both"]
    cfg["audio_source"] = source_keys[idx]

    if cfg["audio_source"] in ("system", "both"):
        print()
        warn("Pour capturer le son système, tu auras besoin de configurer le device monitor.")
        info("Lance 'python main.py devices' après le setup pour trouver le bon index.")
        info("Puis relance 'python main.py config' pour le renseigner.")

    # 4. Modèle Whisper
    step("Quelle précision veux-tu pour la transcription ?")
    whisper_models = [
        ("tiny",   "très rapide, moins précis — idéal pour tester"),
        ("base",   "bon équilibre vitesse/précision — recommandé"),
        ("small",  "plus précis, un peu plus lent"),
        ("medium", "très précis, lent"),
        ("large",  "meilleure précision, très lent (nécessite une bonne GPU)"),
    ]
    idx = choose("Modèle Whisper", whisper_models, default=1)
    cfg["whisper_model"] = whisper_models[idx][0]

    # 5. Fichier de suivi
    step("Où veux-tu sauvegarder les comptes rendus ?")
    default_path = str(Path(__file__).parent / "compte_rendus.md")
    path = ask("Chemin du fichier .md", default=default_path)
    cfg["output_file"] = path

    # Résumé
    print()
    title("📋  Récapitulatif")
    print(f"  Provider LLM   : {BO}{cfg['llm_provider']}{RST}")
    print(f"  Source audio   : {BO}{cfg['audio_source']}{RST}")
    print(f"  Modèle Whisper : {BO}{cfg['whisper_model']}{RST}")
    print(f"  Fichier suivi  : {BO}{cfg['output_file']}{RST}")
    print()

    if ask_yn("Sauvegarder cette configuration ?", default="o"):
        save_config(cfg)
        print()
        ok("Configuration terminée ! Tu peux maintenant lancer une réunion.")
    else:
        warn("Configuration annulée. Relance l'appli pour recommencer.")
        sys.exit(0)

    return cfg

# ─────────────────────────────────────────────
# CONFIG INTERACTIVE
# ─────────────────────────────────────────────
def cmd_config(args=None):
    cfg = load_config() or DEFAULT_CONFIG.copy()
    title("⚙️   Configuration")

    # Provider LLM
    step("Provider LLM")
    providers = ["mistral", "openai", "anthropic", "google"]
    current_idx = providers.index(cfg.get("llm_provider", "mistral")) if cfg.get("llm_provider") in providers else 0
    opts = [
        ("Mistral",   "mistral-large-latest"),
        ("OpenAI",    "GPT-4o"),
        ("Anthropic", "Claude"),
        ("Google",    "Gemini"),
    ]
    idx = choose("Provider", opts, default=current_idx)
    cfg["llm_provider"] = providers[idx]

    # Clé API + modèle du provider sélectionné
    provider = cfg["llm_provider"]
    key_field   = f"{provider}_api_key"
    model_field = f"{provider}_model"
    current_key = cfg.get(key_field, "")
    key_display = ("*" * 8 + current_key[-4:]) if current_key else "(vide)"

    print(f"\n  Clé actuelle : {DIM}{key_display}{RST}")
    new_key = ask("Nouvelle clé API (vide = conserver)")
    if new_key:
        cfg[key_field] = new_key

    new_model = ask("Modèle", default=cfg.get(model_field, ""))
    if new_model:
        cfg[model_field] = new_model

    # Whisper
    step("Transcription Whisper")
    whisper_modes = [
        ("local", "Whisper tourne sur ta machine (pip install openai-whisper torch)"),
        ("api",   "API OpenAI Whisper (nécessite une clé OpenAI)"),
    ]
    current_wmode = 0 if cfg.get("whisper_mode", "local") == "local" else 1
    idx = choose("Mode Whisper", whisper_modes, default=current_wmode)
    cfg["whisper_mode"] = ["local", "api"][idx]

    whisper_model_opts = ["tiny", "base", "small", "medium", "large"]
    current_wmodel = whisper_model_opts.index(cfg.get("whisper_model", "base")) if cfg.get("whisper_model") in whisper_model_opts else 1
    wmodel_full = [
        ("tiny",   "très rapide, moins précis"),
        ("base",   "bon équilibre — recommandé"),
        ("small",  "plus précis, un peu plus lent"),
        ("medium", "très précis, lent"),
        ("large",  "meilleure précision, très lent"),
    ]
    idx = choose("Modèle Whisper", wmodel_full, default=current_wmodel)
    cfg["whisper_model"] = whisper_model_opts[idx]

    # Source audio
    step("Source audio")
    source_opts = [
        ("mic",    "Micro uniquement"),
        ("system", "Son système uniquement (réunion en ligne)"),
        ("both",   "Micro + son système mixés"),
    ]
    source_keys = ["mic", "system", "both"]
    current_src = source_keys.index(cfg.get("audio_source", "mic")) if cfg.get("audio_source") in source_keys else 0
    idx = choose("Source par défaut", source_opts, default=current_src)
    cfg["audio_source"] = source_keys[idx]

    if cfg["audio_source"] in ("mic", "both"):
        val = ask("Index device micro (vide = défaut système)", default=str(cfg.get("mic_device") or ""))
        cfg["mic_device"] = int(val) if val.isdigit() else None

    if cfg["audio_source"] in ("system", "both"):
        info("Lance 'python main.py devices' pour trouver l'index du monitor.")
        val = ask("Index device son système (monitor)", default=str(cfg.get("system_device") or ""))
        cfg["system_device"] = int(val) if val.isdigit() else None

    # Fichier de suivi
    step("Fichier de suivi")
    path = ask("Chemin du fichier .md", default=cfg.get("output_file"))
    if path:
        cfg["output_file"] = path

    print()
    save_config(cfg)

# ─────────────────────────────────────────────
# DEVICES
# ─────────────────────────────────────────────
def cmd_devices(args=None):
    try:
        import sounddevice as sd
    except ImportError:
        err("sounddevice non installé : pip install sounddevice numpy")
        sys.exit(1)

    title("🔊  Devices audio disponibles")
    found = False
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            found = True
            if "monitor" in d["name"].lower():
                icon, color = "🖥 ", G
                hint = "  ← son système"
            elif "mic" in d["name"].lower() or "input" in d["name"].lower():
                icon, color = "🎙 ", C
                hint = "  ← micro"
            else:
                icon, color = "🔊 ", RST
                hint = ""
            print(f"  {BO}[{i:2d}]{RST}  {icon}  {color}{d['name']}{RST}{DIM}{hint}{RST}")

    if not found:
        warn("Aucun device d'entrée trouvé.")
        return

    print()
    separator()
    cfg = load_config() or {}
    print("  Config actuelle :")
    print(f"    audio_source  = {BO}{cfg.get('audio_source', 'mic')}{RST}")
    print(f"    mic_device    = {BO}{cfg.get('mic_device') or 'défaut système'}{RST}")
    print(f"    system_device = {BO}{cfg.get('system_device') or 'non configuré'}{RST}")
    separator()
    info("Les devices 'monitor' capturent le son sortant de tes enceintes/casque.")
    info("Utilise leur index dans 'python main.py config' → Source audio.")

# ─────────────────────────────────────────────
# ENREGISTREMENT
# ─────────────────────────────────────────────
def _record_stream(device, samplerate, frames_list, stop_event):
    import sounddevice as sd

    def callback(indata, frame_count, time_info, status):
        if not stop_event.is_set():
            frames_list.append(indata.copy())

    stream = sd.InputStream(device=device, samplerate=samplerate,
                            channels=1, dtype="float32", callback=callback)
    stream.start()
    stop_event.wait()
    stream.stop()
    stream.close()


def record_audio(cfg, source_override=None) -> str:
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        err("sounddevice/numpy non installé : pip install sounddevice numpy")
        sys.exit(1)

    samplerate    = cfg.get("samplerate", 44100)
    audio_source  = source_override or cfg.get("audio_source", "mic")
    mic_device    = cfg.get("mic_device", None)
    system_device = cfg.get("system_device", None)

    if audio_source == "both" and system_device is None:
        warn("Mode 'both' sélectionné mais aucun device système configuré.")
        warn("Lance 'python main.py devices' pour trouver le monitor.")
        if ask_yn("Continuer avec le micro uniquement ?", default="o"):
            audio_source = "mic"
        else:
            sys.exit(0)

    source_labels = {
        "mic":    "micro",
        "system": f"son système (device {system_device})",
        "both":   "micro + son système",
    }

    title("🔴  Enregistrement")
    info(f"Source : {BO}{source_labels.get(audio_source)}{RST}")
    print()
    print(f"  {BO}{G}  Appuyez sur Entrée pour arrêter l'enregistrement  {RST}")
    print()

    stop_event = threading.Event()
    frames_mic, frames_system = [], []
    threads = []

    if audio_source in ("mic", "both"):
        t = threading.Thread(target=_record_stream,
                             args=(mic_device, samplerate, frames_mic, stop_event),
                             daemon=True)
        t.start()
        threads.append(t)

    if audio_source in ("system", "both"):
        t = threading.Thread(target=_record_stream,
                             args=(system_device, samplerate, frames_system, stop_event),
                             daemon=True)
        t.start()
        threads.append(t)

    # Timer live
    start = time.time()
    stop_input = threading.Event()

    def show_timer():
        while not stop_input.is_set():
            elapsed = time.time() - start
            m, s = divmod(int(elapsed), 60)
            print(f"\r  {R}●{RST}  {BO}{m:02d}:{s:02d}{RST}  en cours...", end="", flush=True)
            time.sleep(0.5)

    timer_thread = threading.Thread(target=show_timer, daemon=True)
    timer_thread.start()

    try:
        input()
    except KeyboardInterrupt:
        pass
    finally:
        stop_input.set()
        stop_event.set()
        for t in threads:
            t.join(timeout=2)

    duration = time.time() - start
    print()
    ok(f"Enregistrement terminé — durée : {int(duration // 60):02d}:{int(duration % 60):02d}")

    # Assembler / mixer
    if frames_mic and (audio_source == "mic" or not frames_system):
        audio = np.concatenate(frames_mic, axis=0)
    elif frames_system and (audio_source == "system" or not frames_mic):
        audio = np.concatenate(frames_system, axis=0)
    else:
        a_mic = np.concatenate(frames_mic, axis=0)
        a_sys = np.concatenate(frames_system, axis=0)
        min_len = min(len(a_mic), len(a_sys))
        audio = a_mic[:min_len] * 0.5 + a_sys[:min_len] * 0.5

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()

    audio_int16 = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(audio_int16.tobytes())

    return tmp.name

# ─────────────────────────────────────────────
# TRANSCRIPTION
# ─────────────────────────────────────────────
def transcribe(audio_path, cfg) -> str:
    mode = cfg.get("whisper_mode", "local")

    if mode == "local":
        try:
            import whisper
        except ImportError:
            err("openai-whisper non installé : pip install openai-whisper torch")
            sys.exit(1)
        with Spinner(f"Transcription Whisper {cfg.get('whisper_model', 'base')}"):
            model = whisper.load_model(cfg.get("whisper_model", "base"))
            result = model.transcribe(audio_path, language="fr")
        return result["text"]
    else:
        try:
            from openai import OpenAI
        except ImportError:
            err("openai non installé : pip install openai")
            sys.exit(1)
        if not cfg.get("openai_api_key"):
            err("Clé API OpenAI manquante pour Whisper API.")
            sys.exit(1)
        with Spinner("Transcription via Whisper API"):
            client = OpenAI(api_key=cfg["openai_api_key"])
            with open(audio_path, "rb") as f:
                result = client.audio.transcriptions.create(
                    model="whisper-1", file=f, language="fr")
        return result.text

# ─────────────────────────────────────────────
# PROMPTS LLM
# ─────────────────────────────────────────────
PROMPT_SYSTEM = """Tu es un assistant spécialisé dans la rédaction de comptes rendus de réunion professionnels.
Tu produis un compte rendu structuré, précis et exploitable, en respectant EXACTEMENT le format fourni.
Tu n'inventes rien. Si une information est absente de la transcription, tu laisses le champ vide ou tu indiques [non mentionné]."""

PROMPT_USER = """Voici la transcription d'une réunion :

---
{transcription}
---

Génère un compte rendu en respectant EXACTEMENT ce format :

---
Date : JJ/MM/AA
Participants :
NOM, Prénom, Rôle

Minutes :
[Retranscription chronologique de tous les éléments clefs abordés.
Inclure les décisions prises ET les éléments qui ont permis de les prendre.]

Actions :
@PERSONNE :
  NOM_TACHE :
    DATE (JJ/MM/AAAA) => description de l'action
---

Exemple :
---
Date : 19/02/26
Participants :
ROMET, Pierre, PI-Lab
CASANOVA, Raphael, Stagiaire

Minutes :
Débrief de l'avancement de Raphael sur le travail réalisé
Discussion sur les papiers lus : thématiques identifiées, premières impressions
Point sur la revue de littérature : deadline vendredi 27/02
Présentation du format du document de synthèse final

Actions :
@Raphael :
  Revue de littérature :
    Vendredi - 20/02/2026 => traiter 1 papier (fiche de synthèse + Excel)
  Document de synthèse :
    Vendredi - 27/02/2026 => rendu du document final
---

Règles :
- Minutes chronologiques, une idée par ligne
- Actions uniquement si date + personne + tâche explicitement mentionnées
- Respecter l'indentation du format Actions
"""

# ─────────────────────────────────────────────
# GÉNÉRATION LLM
# ─────────────────────────────────────────────
def generate(transcription, cfg) -> str:
    provider = cfg.get("llm_provider", "mistral")
    provider_name = {"mistral": "Mistral", "openai": "OpenAI",
                     "anthropic": "Anthropic", "google": "Google"}.get(provider, provider)

    with Spinner(f"Génération du compte rendu via {provider_name}"):
        if provider == "mistral":
            return _generate_mistral(transcription, cfg)
        elif provider == "openai":
            return _generate_openai(transcription, cfg)
        elif provider == "anthropic":
            return _generate_anthropic(transcription, cfg)
        elif provider == "google":
            return _generate_google(transcription, cfg)
        else:
            err(f"Provider inconnu : {provider}")
            sys.exit(1)


def _generate_mistral(transcription, cfg):
    import requests
    key = cfg.get("mistral_api_key")
    if not key:
        err("Clé API Mistral manquante. Lance : python main.py config")
        sys.exit(1)
    resp = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": cfg.get("mistral_model", "mistral-large-latest"),
            "messages": [
                {"role": "system", "content": PROMPT_SYSTEM},
                {"role": "user",   "content": PROMPT_USER.format(transcription=transcription)},
            ],
            "temperature": 0.2,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _generate_openai(transcription, cfg):
    from openai import OpenAI
    key = cfg.get("openai_api_key")
    if not key:
        err("Clé API OpenAI manquante. Lance : python main.py config")
        sys.exit(1)
    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model=cfg.get("openai_model", "gpt-4o"),
        messages=[
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user",   "content": PROMPT_USER.format(transcription=transcription)},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content


def _generate_anthropic(transcription, cfg):
    import anthropic
    key = cfg.get("anthropic_api_key")
    if not key:
        err("Clé API Anthropic manquante. Lance : python main.py config")
        sys.exit(1)
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=cfg.get("anthropic_model", "claude-sonnet-4-6"),
        max_tokens=4096,
        system=PROMPT_SYSTEM,
        messages=[{"role": "user", "content": PROMPT_USER.format(transcription=transcription)}],
    )
    return resp.content[0].text


def _generate_google(transcription, cfg):
    import google.generativeai as genai
    key = cfg.get("google_api_key")
    if not key:
        err("Clé API Google manquante. Lance : python main.py config")
        sys.exit(1)
    genai.configure(api_key=key)
    model = genai.GenerativeModel(
        model_name=cfg.get("google_model", "gemini-1.5-pro"),
        system_instruction=PROMPT_SYSTEM,
    )
    resp = model.generate_content(
        PROMPT_USER.format(transcription=transcription),
        generation_config={"temperature": 0.2},
    )
    return resp.text

# ─────────────────────────────────────────────
# SAUVEGARDE
# ─────────────────────────────────────────────
def save_cr(content, cfg):
    filepath = Path(cfg["output_file"])
    separator = "\n\n" + "─" * 60 + "\n\n"
    existing = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
    filepath.write_text(
        content + (separator + existing if existing else ""),
        encoding="utf-8"
    )
    ok(f"Compte rendu ajouté en haut de {BO}{filepath}{RST}")

# ─────────────────────────────────────────────
# COMMANDE PRINCIPALE
# ─────────────────────────────────────────────
def cmd_run(args):
    banner()

    # ── Vérification config ──────────────────
    cfg = load_config()

    if cfg is None:
        print()
        warn("Aucun fichier de configuration trouvé.")
        if ask_yn("Lancer le wizard de configuration maintenant ?", default="o"):
            cfg = run_setup_wizard()
        else:
            err("Configuration requise pour continuer.")
            sys.exit(1)
    elif not config_is_valid(cfg):
        print()
        warn(f"La clé API pour '{cfg.get('llm_provider')}' est manquante.")
        if ask_yn("Ouvrir la configuration maintenant ?", default="o"):
            cmd_config()
            cfg = load_config()
        else:
            err("Clé API requise pour continuer.")
            sys.exit(1)

    # ── Choix source audio ───────────────────
    if not args.file and not args.transcription:
        step("Source audio pour cette réunion")
        source_opts = [
            ("Micro",                f"défaut config : {cfg.get('audio_source', 'mic')}"),
            ("Son système",          "réunion en ligne (Teams, Zoom, Meet...)"),
            ("Micro + son système",  "réunion en ligne où tu parles aussi"),
            ("Charger un fichier",   "fichier audio existant (.mp3, .wav, .m4a...)"),
        ]
        idx = choose("Source", source_opts, default=["mic","system","both"].index(cfg.get("audio_source","mic")) if cfg.get("audio_source") in ["mic","system","both"] else 0)
        source_map = {0: "mic", 1: "system", 2: "both", 3: "file"}
        chosen_source = source_map[idx]

        if chosen_source == "file":
            audio_path = ask("Chemin du fichier audio")
            if not audio_path or not Path(audio_path).exists():
                err(f"Fichier introuvable : {audio_path}")
                sys.exit(1)
            tmp_to_delete = None
        else:
            audio_path = record_audio(cfg, source_override=chosen_source)
            tmp_to_delete = audio_path

    elif args.file:
        info(f"Fichier audio : {args.file}")
        audio_path = args.file
        tmp_to_delete = None
    else:
        audio_path = None
        tmp_to_delete = None

    # ── Transcription ────────────────────────
    if args.transcription:
        transcription = Path(args.transcription).read_text(encoding="utf-8")
        ok("Transcription chargée depuis fichier.")
    else:
        transcription = transcribe(audio_path, cfg)

    # Afficher + option édition
    title("📝  Transcription")
    print(DIM + transcription + RST)

    if not args.yes:
        if ask_yn("Corriger la transcription avant génération ?"):
            editor = os.environ.get("EDITOR", "nano")
            with tempfile.NamedTemporaryFile(suffix=".txt", mode="w",
                                             delete=False, encoding="utf-8") as tf:
                tf.write(transcription)
                tf_path = tf.name
            os.system(f"{editor} {tf_path}")
            transcription = Path(tf_path).read_text(encoding="utf-8")
            os.unlink(tf_path)
            ok("Transcription mise à jour.")

    # ── Génération ───────────────────────────
    compte_rendu = generate(transcription, cfg)

    title("📋  Compte Rendu Généré")
    print(compte_rendu)

    if not args.yes:
        if ask_yn("Corriger le compte rendu avant sauvegarde ?"):
            editor = os.environ.get("EDITOR", "nano")
            with tempfile.NamedTemporaryFile(suffix=".md", mode="w",
                                             delete=False, encoding="utf-8") as tf:
                tf.write(compte_rendu)
                tf_path = tf.name
            os.system(f"{editor} {tf_path}")
            compte_rendu = Path(tf_path).read_text(encoding="utf-8")
            os.unlink(tf_path)
            ok("Compte rendu mis à jour.")

    # ── Sauvegarde ───────────────────────────
    if args.yes or ask_yn(f"Sauvegarder dans {cfg['output_file']} ?", default="o"):
        save_cr(compte_rendu, cfg)
    else:
        info("Non sauvegardé.")

    if tmp_to_delete and os.path.exists(tmp_to_delete):
        os.unlink(tmp_to_delete)

    print()


def cmd_transcribe_only(args):
    cfg = load_config() or DEFAULT_CONFIG.copy()
    text = transcribe(args.file, cfg)
    print(text)


def cmd_generate_only(args):
    cfg = load_config()
    if not config_is_valid(cfg):
        err("Config invalide ou manquante. Lance : python main.py config")
        sys.exit(1)
    transcription = Path(args.file).read_text(encoding="utf-8")
    cr = generate(transcription, cfg)
    title("📋  Compte Rendu")
    print(cr)
    if ask_yn(f"Sauvegarder dans {cfg['output_file']} ?", default="o"):
        save_cr(cr, cfg)

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="🎙️  CRon — Générateur de compte rendu de réunion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
commandes :
  (aucune)              menu interactif — enregistre, transcrit, génère
  config                configurer le provider LLM, les clés API, la source audio
  devices               lister les devices audio (utile pour trouver le monitor)
  transcribe -f FILE    transcrire un fichier audio sans générer de CR
  generate -f FILE      générer un CR depuis un fichier texte de transcription

options rapides :
  -f FILE               fichier audio source (skip l'enregistrement)
  -t FILE               fichier texte de transcription (skip Whisper)
  -s mic|system|both    source audio pour cette session (override config)
  -y                    mode non-interactif (accepte tout)
        """
    )

    subparsers = parser.add_subparsers(dest="cmd")

    parser.add_argument("-f", "--file")
    parser.add_argument("-t", "--transcription")
    parser.add_argument("-y", "--yes", action="store_true")
    parser.add_argument("-s", "--source", choices=["mic", "system", "both"])

    subparsers.add_parser("config")
    subparsers.add_parser("devices")

    sub_trans = subparsers.add_parser("transcribe")
    sub_trans.add_argument("-f", "--file", required=True)

    sub_gen = subparsers.add_parser("generate")
    sub_gen.add_argument("-f", "--file", required=True)

    args = parser.parse_args()

    if args.cmd == "config":
        cmd_config(args)
    elif args.cmd == "devices":
        cmd_devices(args)
    elif args.cmd == "transcribe":
        cmd_transcribe_only(args)
    elif args.cmd == "generate":
        cmd_generate_only(args)
    else:
        cmd_run(args)


if __name__ == "__main__":
    main()
