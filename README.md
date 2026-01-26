# ALARMv3

ALARMv3 - Advanced Learning and Retrieval Monitoring System v3

## POC (Proof of Concept)

This repository includes a complete POC framework to validate ALARMv3 design choices. See [docs/POC_PLAN_ALARMv3.md](docs/POC_PLAN_ALARMv3.md) for details.

### Quick Start

1. **Setup Environment**
   ```bash
   ./scripts/setup_env.sh
   source .venv/bin/activate
   ```

2. **Run Indexing Pipeline**
   ```bash
   # Create a demo app or use an existing codebase
   mkdir -p /tmp/demo_app
   echo "# Demo code" > /tmp/demo_app/main.py
   
   # Run indexing
   ./scripts/run_index_and_log.sh /tmp/demo_app ./out
   ```

3. **Count Vectors in Database**
   ```bash
   python scripts/count_chroma.py ./out/rag_db
   ```

4. **Measure Query Latency**
   ```bash
   # Find session_id from the created session file name
   SESSION_ID=$(ls ./out/session_*.json | head -1 | sed 's/.*session_//' | sed 's/.json//')
   
   # Measure latency with 100 queries
   ./scripts/measure_cli_query.sh $SESSION_ID "How does authentication work?" 100
   ```

### POC Deliverables

- **Documentation**: 
  - [POC Plan](docs/POC_PLAN_ALARMv3.md) - Scope, timeline, and acceptance criteria
  - [Metrics](docs/METRICS.md) - Operational and quality metrics template
  - [Experiment Matrix](docs/EXPERIMENT_MATRIX.md) - Experiment tracking structure

- **Scripts**:
  - `scripts/setup_env.sh` - Environment setup
  - `scripts/run_index_and_log.sh` - Indexing pipeline with logging
  - `scripts/count_chroma.py` - Vector count utility
  - `scripts/measure_cli_query.sh` - Query latency measurement

### POC Goals

1. Reproducible indexing pipeline metrics
2. Retrieval quality comparison across embedding models
3. Vector DB performance evaluation (Chroma, pgvector, FAISS)
4. Serving latency measurement and SLO validation (target: p95 < 200ms)
5. Monitoring baseline and drift detection
6. CI/CD reproducibility with MLflow tracking

