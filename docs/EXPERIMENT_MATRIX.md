# ALARMv3 Experiment Matrix

Columns:
- experiment_id
- app (demo / real path)
- embedding_model (all-MiniLM / CodeBERT / OpenAI)
- vector_db (Chroma / pgvector / FAISS)
- index_time_sec
- chunk_count
- vector_count
- storage_mb
- query_p50_ms
- query_p95_ms
- query_p99_ms
- precision_at_5
- recall_at_5
- mrr
- git_sha
- mlflow_run_id
- timestamp
- notes

## Experiments

| experiment_id | app | embedding_model | vector_db | index_time_sec | chunk_count | vector_count | storage_mb | query_p50_ms | query_p95_ms | query_p99_ms | precision_at_5 | recall_at_5 | mrr | git_sha | mlflow_run_id | timestamp | notes |
|---------------|-----|----------------|-----------|----------------|-------------|--------------|------------|--------------|--------------|--------------|----------------|-------------|-----|---------|---------------|-----------|-------|
| exp_001 | demo_app | all-MiniLM-L6-v2 | Chroma | | | | | | | | | | | | | | Baseline |
| exp_002 | demo_app | CodeBERT | Chroma | | | | | | | | | | | | | | Code-tuned model |
| exp_003 | demo_app | all-MiniLM-L6-v2 | pgvector | | | | | | | | | | | | | | Postgres backend |
| exp_004 | demo_app | all-MiniLM-L6-v2 | FAISS | | | | | | | | | | | | | | In-memory prototype |

## Template for New Experiments

```json
{
  "experiment_id": "exp_XXX",
  "app": "/path/to/app",
  "embedding_model": "model_name",
  "vector_db": "db_type",
  "config": {
    "chunk_size": 512,
    "overlap": 128,
    "top_k": 5
  },
  "results": {
    "indexing": {
      "time_sec": 0.0,
      "chunk_count": 0,
      "vector_count": 0,
      "storage_mb": 0.0
    },
    "query_latency": {
      "p50_ms": 0.0,
      "p95_ms": 0.0,
      "p99_ms": 0.0
    },
    "retrieval_quality": {
      "precision_at_5": 0.0,
      "recall_at_5": 0.0,
      "mrr": 0.0
    }
  },
  "metadata": {
    "git_sha": "",
    "mlflow_run_id": "",
    "timestamp": "",
    "notes": ""
  }
}
```
