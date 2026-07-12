#!/usr/bin/env bash
set -e

LLM_MODEL="${LLM_MODEL:-qwen2.5:14b}"

ollama serve &

until curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; do
    sleep 1
done

ollama pull "${LLM_MODEL}"

exec python3 /app/app.py
