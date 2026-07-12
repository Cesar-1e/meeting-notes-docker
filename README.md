# AI Meeting Notes (local, GPU, Docker)

Pipeline local y **headless** que toma los audios de una carpeta y genera, para cada uno, una
minuta en Markdown. Todo corre dentro de **un solo contenedor**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
en GPU para transcribir + [Ollama](https://ollama.com) para estructurar el texto.

Flujo por archivo: audio → transcripción (Whisper, GPU) → minuta en Markdown (LLM local) →
se escribe `<nombre>_notas.md` junto al audio.

Hardware objetivo: RTX 5060 Ti 16 GB (Blackwell / sm_120), Docker sobre WSL2.

## Estructura

```
meeting-notes-docker/
├── Dockerfile            # nvidia/cuda:12.8.0-cudnn-runtime + Python + Ollama
├── docker-compose.yml    # servicio, volúmenes de caché y reserva de GPU
├── entrypoint.sh         # arranca Ollama, hace pull del modelo y lanza app.py
├── requirements.txt      # dependencias pinneadas
├── app.py                # el pipeline (batch sobre audios/)
├── prompts/              # plantillas de prompt por tipo de reunión
│   ├── general.md.example
│   ├── standup.md.example
│   ├── retro.md.example
│   └── cliente.md.example
├── audios/               # dejá acá tus audios; las minutas se escriben acá también
└── README.md
```

## Requisitos del host

- Driver NVIDIA reciente en Windows (para Blackwell / CUDA 12.8).
- `nvidia-container-toolkit` instalado en la distro WSL2.
- Docker con soporte de GPU habilitado.

Verificá que Docker ve la GPU antes de empezar:

```bash
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu22.04 nvidia-smi
```

Si ese comando muestra tu GPU, estás listo.

## Cómo correr

```bash
# 1. Build de la imagen
docker compose build

# 2. Dejá tus audios o videos en ./audios/ (mp3, wav, m4a, ogg, flac, mp4, mkv)

# 3. Corré el pipeline
docker compose run --rm meeting-notes
```

En la primera corrida se descargan el modelo de Whisper (`large-v3`) y el LLM (`qwen3.5:9b`);
quedan cacheados en los volúmenes `whisper-cache` y `ollama-models`, así que las corridas
siguientes no vuelven a descargar nada.

Al terminar, por cada `audios/<nombre>.<ext>` vas a tener un `audios/<nombre>_notas.md`.

Los videos (`.mp4`, `.mkv`) también se procesan: antes de transcribir se les extrae la pista de
audio con ffmpeg (WAV 16 kHz mono, en un temporal que se descarta al terminar).

Las corridas son incrementales: si ya existe `<nombre>_notas.md`, ese audio/video se salta.
Para regenerar una minuta, borrá (o renombrá) el `.md` y volvé a correr.

## Tipos de reunión (prompts)

Cada tipo de reunión tiene su plantilla en `prompts/<tipo>.md` (texto plano con la instrucción
de sistema para el LLM).

En el repo solo se versionan los ejemplos (`prompts/*.md.example`); los `.md` reales están en
`.gitignore` porque son personales de cada uno. En el primer arranque, el entrypoint crea
automáticamente cada `<tipo>.md` que falte copiándolo de su `.md.example` — después podés
editarlos libremente sin que git los toque. Para volver al ejemplo original, borrá tu `.md`
y volvé a correr.

La selección de plantilla funciona así, en orden de precedencia:

1. **Sufijo en el nombre del archivo:** si el audio termina en `__<tipo>` antes de la extensión,
   se usa `prompts/<tipo>.md`. Ejemplo: `daily-2026-07-11__standup.mp3` → `prompts/standup.md`.
2. **Default por entorno:** sin sufijo, se usa la variable `PROMPT_TEMPLATE` (default `general`).
3. **Fallback:** si la plantilla resuelta no existe, se emite un warning y se usa `prompts/general.md`.

Así una misma carpeta puede mezclar reuniones de distinto tipo y cada una se procesa con su plantilla.

### Agregar un nuevo tipo de reunión

1. Creá `prompts/<tipo>.md` con la instrucción para el LLM (mirá los `.md.example` como referencia).
2. Nombrá el audio `loquesea__<tipo>.mp3` (o la extensión que sea).

Como `./prompts` está montado como volumen, podés crear o editar plantillas sin rebuildear la imagen.
Si querés compartir un tipo de reunión con el equipo, versioná también un `prompts/<tipo>.md.example`.

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `AUDIO_DIR` | `/app/audios` | Carpeta donde se buscan los audios |
| `OUTPUT_DIR` | `/app/audios` | Carpeta donde se escriben las minutas |
| `PROMPTS_DIR` | `/app/prompts` | Carpeta de plantillas de prompt |
| `WHISPER_MODEL` | `large-v3` | Modelo de faster-whisper |
| `COMPUTE_TYPE` | `float16` | Tipo de cómputo de Whisper. **No cambiar:** en Blackwell `int8` crashea con `CUBLAS_STATUS_NOT_SUPPORTED` |
| `LANGUAGE` | `es` | Idioma de la transcripción |
| `PROMPT_TEMPLATE` | `general` | Plantilla default cuando el audio no tiene sufijo `__<tipo>` |
| `LLM_MODEL` | `qwen3.5:9b` | Modelo de Ollama para generar la minuta |
| `NUM_CTX` | `16384` | Ventana de contexto del LLM en tokens. Si la minuta sale cortada, subilo (32768 para reuniones de +1 h); más contexto = más VRAM |
| `NUM_GPU` | *(auto)* | Cantidad de capas del LLM que van a la GPU; el resto corre en CPU/RAM. Vacío = Ollama decide solo |
| `OLLAMA_HOST` | `http://localhost:11434` | URL del servidor Ollama |

Ejemplo con overrides:

```bash
LLM_MODEL=llama3.1:8b PROMPT_TEMPLATE=retro docker compose run --rm meeting-notes
```

## Aprovechar la RAM: modelos más grandes y más contexto

La VRAM (16 GB) limita qué modelo y cuánto contexto entran en la GPU, pero no es un techo duro:

- **Offload a RAM (automático):** si el modelo no cabe en VRAM, Ollama pone en la GPU las capas
  que quepan y el resto corre en CPU usando la RAM. Con 96 GB de RAM podés correr modelos grandes
  directamente — solo cambia la velocidad (las capas en CPU son mucho más lentas):

  ```bash
  LLM_MODEL=qwen3.5:32b docker compose run --rm meeting-notes
  ```

  Con `NUM_GPU` podés forzar cuántas capas van a la GPU si el reparto automático no convence.
- **La "memoria compartida de GPU" de Windows NO es el camino:** ese spillover de VRAM a RAM del
  driver (WDDM) no aplica dentro de WSL2 y, cuando actúa, mueve datos por PCIe sin criterio y
  degrada todo. El offload por capas de Ollama hace lo mismo pero de forma controlada y eficiente.
- **El pipeline procesa en dos fases** justamente para maximizar la VRAM disponible: primero
  transcribe todos los audios con Whisper, descarga Whisper de la GPU (~3 GB liberados) y recién
  entonces genera las minutas con el LLM.
- **KV cache más chico = más contexto:** para reuniones muy largas podés cuantizar el KV cache y
  duplicar el contexto que entra en la misma VRAM:

  ```bash
  OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 NUM_CTX=32768 docker compose run --rm meeting-notes
  ```

## Notas técnicas

- **Imagen base fija:** `nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04` (incluye cuDNN 9; desde
  CUDA 12.4 el tag ya no lleva el número de versión de cuDNN). CUDA 12.8 es el piso que soporta
  Blackwell y coincide con lo que CTranslate2 espera (CUDA 12 / cuDNN 9). No usar `latest` ni CUDA 13.
- Ollama corre **dentro** del contenedor, arrancado por el entrypoint; no depende del host.
- El contenedor es efímero (`--rm`); los modelos persisten solo gracias a los volúmenes nombrados.
- Un error en un archivo (audio corrupto, timeout del LLM, etc.) no corta el batch: se loguea y
  se sigue con el siguiente.
- **Minutas cortadas a mitad de frase:** Ollama usa por defecto una ventana de contexto de 4096
  tokens; con transcripciones largas trunca la entrada y corta la salida. Por eso la llamada a
  `/api/generate` pasa `num_ctx` explícito (variable `NUM_CTX`, default 16384). Si aun así sale
  incompleta, subí `NUM_CTX` — el límite práctico es la VRAM (el KV cache crece con el contexto).
