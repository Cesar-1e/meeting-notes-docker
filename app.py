import os
import sys
import time
from pathlib import Path

import requests
from faster_whisper import WhisperModel

AUDIO_DIR = os.environ.get("AUDIO_DIR", "/app/audios")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/app/audios")
PROMPTS_DIR = os.environ.get("PROMPTS_DIR", "/app/prompts")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")
COMPUTE_TYPE = os.environ.get("COMPUTE_TYPE", "float16")
LANGUAGE = os.environ.get("LANGUAGE", "es")
PROMPT_TEMPLATE = os.environ.get("PROMPT_TEMPLATE", "general")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:14b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4"}


def resolve_template(audio_path: Path) -> Path:
    """Resuelve la plantilla de prompt para un audio.

    Precedencia:
    1. Sufijo __<tipo> en el nombre del archivo (ej. reunion__standup.mp3).
    2. Variable de entorno PROMPT_TEMPLATE.
    3. Fallback a general.md si la plantilla resuelta no existe.
    """
    stem = audio_path.stem
    if "__" in stem:
        template_name = stem.rsplit("__", 1)[1]
    else:
        template_name = PROMPT_TEMPLATE

    template_path = Path(PROMPTS_DIR) / f"{template_name}.md"
    if not template_path.exists():
        print(
            f"  WARNING: plantilla '{template_path}' no existe, "
            f"usando 'general.md'"
        )
        template_path = Path(PROMPTS_DIR) / "general.md"
    return template_path


def transcribe(model: WhisperModel, audio_path: Path) -> str:
    segments, _info = model.transcribe(str(audio_path), language=LANGUAGE)
    return "".join(segment.text for segment in segments).strip()


def generate_notes(system_prompt: str, transcript: str) -> str:
    prompt = f"{system_prompt}\n\nTranscripción:\n{transcript}"
    response = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
        timeout=600,
    )
    response.raise_for_status()
    return response.json()["response"]


def main() -> None:
    audio_dir = Path(AUDIO_DIR)
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_files = sorted(
        p
        for p in audio_dir.iterdir()
        if p.is_file()
        and not p.name.startswith(".")
        and p.suffix.lower() in AUDIO_EXTENSIONS
    )

    if not audio_files:
        print(f"No se encontraron audios en {audio_dir}. Nada que hacer.")
        return

    print(f"Encontrados {len(audio_files)} audio(s) en {audio_dir}")
    print(f"Cargando Whisper '{WHISPER_MODEL}' (device=cuda, compute_type={COMPUTE_TYPE})...")
    model = WhisperModel(WHISPER_MODEL, device="cuda", compute_type=COMPUTE_TYPE)
    print("Modelo cargado.\n")

    total = len(audio_files)
    ok, failed = 0, 0

    for i, audio_path in enumerate(audio_files, start=1):
        print(f"[{i}/{total}] {audio_path.name}")
        try:
            template_path = resolve_template(audio_path)
            print(f"  Plantilla: {template_path.name}")
            system_prompt = template_path.read_text(encoding="utf-8")

            start = time.time()
            transcript = transcribe(model, audio_path)
            elapsed = time.time() - start
            print(
                f"  Transcripción: {elapsed:.1f}s, "
                f"{len(transcript)} caracteres"
            )

            print(f"  Generando minuta con {LLM_MODEL}...")
            notes = generate_notes(system_prompt, transcript)

            output_path = output_dir / f"{audio_path.stem}_notas.md"
            output_path.write_text(notes, encoding="utf-8")
            print(f"  OK: {output_path.name}\n")
            ok += 1
        except requests.RequestException as e:
            print(f"  ERROR llamando a Ollama para {audio_path.name}: {e}\n")
            failed += 1
        except Exception as e:
            print(f"  ERROR procesando {audio_path.name}: {e}\n")
            failed += 1

    print(f"Listo: {ok} exitoso(s), {failed} con error, de {total} audio(s).")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
