# ALARMv3 POC Plan

Purpose
- Execute a focused set of experiments to validate ALARMv3 design choices: embeddings, vector DB, indexing performance, retrieval quality, and serving latency.

POC scope (minimum)
1. **Reproducible indexing pipeline**: measure index time, chunk/vector counts, and rag_db size.
2. **Retrieval quality vs model choice**: compare all-MiniLM vs at least one code-tuned model (e.g., CodeBERT) on a gold query set.
3. **Vector DB feasibility**: pilot Postgres+pgvector, Chroma (local), and a FAISS prototype. Measure indexing time, query p95/p99, and storage.
4. **Serving & latency**: measure CLI/HTTP query p50/p95/p99 and validate SLOs (target p95 < 200ms for pilot scale).
5. **Monitoring & drift baseline**: produce daily top-k similarity histogram and PSI/K-S tests on one week baseline cadence.
6. **CI/CD & reproducibility**: ensure MLflow records dataset snapshot, docker tag, git SHA on runs.

## Deliverables
- Metrics for indexing performance (time, chunk counts, storage size)
- Retrieval quality comparison across embedding models
- Vector DB performance comparison (Postgres+pgvector, Chroma, FAISS)
- Latency measurements (p50, p95, p99)
- Monitoring baseline data and drift detection metrics
- CI/CD reproducibility artifacts (MLflow runs, git SHAs, docker tags)

## Timeline & Resource Estimate
- **Setup & demo indexing**: 1–2 hours (single machine)
- **Model comparison for two models**: 2–4 hours (download models & run retrieval eval)
- **Vector DB pilot** (pgvector vs Chroma vs FAISS quickbench): 1–2 days (depends on infra)
- **Serving latency tests + baseline monitoring job**: 4–8 hours

## Acceptance Criteria
- All scripts execute successfully on target environment
- Metrics are collected and documented in METRICS.md
- Experiment results are recorded in EXPERIMENT_MATRIX.md
- Results validate or invalidate design decisions with data
- Reproducibility is demonstrated via git SHA and MLflow tracking
