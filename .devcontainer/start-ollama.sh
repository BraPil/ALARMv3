#!/usr/bin/env bash
# Start Ollama daemon and ensure nomic-embed-text is available.
# Runs as postStartCommand — after network is up, before dev work begins.
set -e

# Start the daemon in background if not already running
if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
  echo "[ollama] Starting daemon..."
  nohup ollama serve > /tmp/ollama.log 2>&1 &
  # Wait for it to be ready (up to 30s)
  for i in $(seq 1 30); do
    if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
      echo "[ollama] Ready."
      break
    fi
    sleep 1
  done
else
  echo "[ollama] Already running."
fi

# Pull nomic-embed-text if not present
if ! ollama list | grep -q "nomic-embed-text"; then
  echo "[ollama] Pulling nomic-embed-text (~274MB, CPU-only)..."
  ollama pull nomic-embed-text
  echo "[ollama] nomic-embed-text ready."
else
  echo "[ollama] nomic-embed-text already present."
fi
