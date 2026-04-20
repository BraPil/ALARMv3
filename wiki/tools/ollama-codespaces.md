# Ollama in GitHub Codespaces
> **Status**: current
> **Last updated**: 2026-04-20
> **Tags**: ollama, codespaces, embeddings, devcontainer, nomic-embed-text

How to run Ollama's `nomic-embed-text` inside a GitHub Codespace for ALARMv3 Phase 2 RAG embeddings. Verified working 2026-04-20.

## Why Ollama in Codespaces?

The board decision (Decision #4) mandates local embeddings via Ollama — no external API calls for the embedding step. This keeps the embedding cost zero and ensures the code never leaves the environment. `nomic-embed-text` is 274MB and runs comfortably on CPU in a standard Codespace (4-core, 8GB RAM).

## Key constraints

- **No systemd**: Codespaces containers don't run systemd. The standard `ollama serve` systemd service can't be used. Run as a background process instead.
- **No GPU**: Standard Codespaces are CPU-only. `nomic-embed-text` is fast enough on CPU for development workloads (~5–20ms per chunk).
- **Model cache persists**: The pulled model is stored in `~/.ollama/models/` which survives container restarts (as long as the Codespace isn't rebuilt). Pull once per Codespace lifetime.
- **Port 11434**: Ollama listens on `127.0.0.1:11434` by default. No auth required for local-only use.

## devcontainer setup

`.devcontainer/devcontainer.json` handles install and startup:

```json
{
  "postCreateCommand": "... curl -fsSL https://ollama.com/install.sh | sh",
  "postStartCommand": "bash .devcontainer/start-ollama.sh"
}
```

`.devcontainer/start-ollama.sh`:
1. Checks if Ollama is already running (idempotent — safe to call on every start)
2. Starts `ollama serve` in background via `nohup`
3. Waits up to 30 seconds for the API to be ready
4. Pulls `nomic-embed-text` if not already cached

## Manual setup (existing Codespace)

```bash
# Install Ollama (one-time)
curl -fsSL https://ollama.com/install.sh | sh

# Start the daemon (each session)
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 3

# Pull the model (one-time per Codespace lifetime)
ollama pull nomic-embed-text

# Verify
curl http://localhost:11434/api/tags
# → {"models":[{"name":"nomic-embed-text:latest",...}]}
```

## Verifying embeddings work

```python
import ollama
resp = ollama.embeddings(model="nomic-embed-text", prompt="Hello, legacy codebase")
print(len(resp["embedding"]))  # → 768
```

## ALARMv3 integration

`knowledge.py` uses the `ollama` Python client (already in `pyproject.toml`):

```python
import ollama

def _embed(self, text: str) -> list[float]:
    resp = ollama.embeddings(model=OLLAMA_MODEL, prompt=text)
    return resp["embedding"]
```

The `OLLAMA_BASE_URL` and `OLLAMA_MODEL` constants in `knowledge.py` are configurable via `.alarmv3/config.yaml`.

If Ollama is unreachable, `KnowledgeBuilder.build()` raises `OllamaUnavailableError` with a clear message pointing to this wiki page. Tests that require Ollama use `pytest.mark.skipif(not _ollama_running(), ...)`.

## Performance notes (CPU, nomic-embed-text)

| Batch size | Approx. time |
|-----------|-------------|
| 1 chunk | ~5–20ms |
| 100 chunks | ~0.5–2s |
| 1000 chunks | ~5–20s |
| 50k LOC codebase (~2000 chunks) | ~10–40s |

Well within the Phase 1 target of <2 min for 50k LOC total pipeline.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Connection refused :11434` | `ollama serve` not running. Re-run `start-ollama.sh`. |
| `model not found: nomic-embed-text` | Run `ollama pull nomic-embed-text` |
| Slow first embed | Normal — model loads into RAM on first call (~1–2s warmup) |
| `nohup: failed to run command` | Ollama binary not on PATH. Re-run install script. |

## See also
- [Phase 2 Plan](../project/phase2-plan.md)
- [Board Decisions](../architecture/board-decisions.md) — Decision #4
