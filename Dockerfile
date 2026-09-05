FROM python:3.12-slim

# System deps: build tools for packages that compile native extensions
# (faiss, sentence-transformers' tokenizers, etc.), plus ffmpeg for
# any audio processing edge-tts / TTS features may need.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer is cached across code-only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# Now copy the rest of the app.
COPY . .

# Render mounts the persistent disk at this path (see render.yaml) so
# chats/users/projects survive restarts and redeploys.
RUN mkdir -p /app/database

ENV RENDER=true
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["python", "run.py"]