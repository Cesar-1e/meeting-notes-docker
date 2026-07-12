#!/usr/bin/env bash
set -e

LLM_MODEL="${LLM_MODEL:-qwen3.5:9b}"
PROMPTS_DIR="${PROMPTS_DIR:-/app/prompts}"

# Seed: crea cada prompt real a partir de su .md.example si todavía no existe.
shopt -s nullglob
for example in "${PROMPTS_DIR}"/*.md.example; do
    target="${example%.example}"
    if [ ! -e "${target}" ]; then
        cp "${example}" "${target}"
        echo "Prompt creado desde example: $(basename "${target}")"
    fi
done
shopt -u nullglob

ollama serve &

until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
    sleep 1
done

ollama pull "${LLM_MODEL}"

exec python3 /app/app.py
