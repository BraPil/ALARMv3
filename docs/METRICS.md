# ALARMv3 METRICS (POC starter)

Operational metrics (collect in Prometheus/Grafana)
- Query latency: p50, p95, p99 (ms) — SLO target p95 < 200ms for pilot.
- QPS (requests/sec) and concurrency.
- Index job duration (seconds) & success rate (%).
- Vector DB storage size (MB/GB).
- Chunk count per indexed app.
- Vector count in collection.

## Indexing Metrics
| Metric | Value | Unit | Notes |
|--------|-------|------|-------|
| Index time | | seconds | Time to index entire codebase |
| Chunk count | | count | Number of code chunks extracted |
| Vector count | | count | Number of vectors in DB |
| Storage size | | MB | Size of rag_db/persistent storage |
| Chunks/second | | rate | Indexing throughput |

## Retrieval Quality Metrics
| Model | Precision@5 | Recall@5 | MRR | Notes |
|-------|-------------|----------|-----|-------|
| all-MiniLM-L6-v2 | | | | Baseline |
| CodeBERT | | | | Code-tuned |
| OpenAI ada-002 | | | | Commercial baseline |

## Query Latency Metrics
| Percentile | Latency (ms) | Notes |
|------------|--------------|-------|
| p50 | | Median latency |
| p95 | | SLO target < 200ms |
| p99 | | Tail latency |

## Vector DB Comparison
| DB Type | Index Time (s) | Query p95 (ms) | Storage (MB) | Notes |
|---------|---------------|----------------|--------------|-------|
| Chroma (local) | | | | Local file-based |
| Postgres+pgvector | | | | Production-ready |
| FAISS | | | | In-memory prototype |

## Monitoring & Drift Metrics
- Top-k similarity distribution (daily histogram)
- PSI (Population Stability Index) over 1-week baseline
- K-S test statistic for distribution drift
- Alert thresholds for production deployment
