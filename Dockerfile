FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04

ENV HF_HOME=/root/.cache/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip \
        python3-dev \
        ffmpeg \
        curl \
        ca-certificates \
        zstd \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://ollama.com/install.sh | sh

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY app.py entrypoint.sh ./
COPY prompts/ ./prompts/

RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
