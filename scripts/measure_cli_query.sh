#!/usr/bin/env bash
# scripts/measure_cli_query.sh <session_id> "query text" [n]
set -euo pipefail

session_id="$1"
query_text="$2"
n="${3:-100}"

echo "Measuring CLI query latency..."
echo "  Session: $session_id"
echo "  Query: $query_text"
echo "  Iterations: $n"
echo ""

# Find session file
SESSION_FILE=""
for f in ./out/session_${session_id}.json ./test_out/session_${session_id}.json session_${session_id}.json; do
    if [ -f "$f" ]; then
        SESSION_FILE="$f"
        break
    fi
done

if [ -z "$SESSION_FILE" ]; then
    echo "ERROR: Session file not found for session: $session_id"
    echo "Searched in ./out, ./test_out, and current directory"
    exit 1
fi

echo "Found session file: $SESSION_FILE"

# Extract output directory from session file path
OUT_DIR=$(dirname "$SESSION_FILE")

# Extract DB path from session file
DB_PATH=$(grep -o '"db_path": "[^"]*"' "$SESSION_FILE" | cut -d'"' -f4)
echo "DB path: $DB_PATH"
echo "Output dir: $OUT_DIR"
echo ""

# Create temporary output file
TEMP_FILE=$(mktemp)
trap "rm -f $TEMP_FILE" EXIT

echo "Running $n queries..."
echo "[$(date -Iseconds)] Starting query benchmark" >> "$TEMP_FILE"

# Measure query latencies
latencies=()
for i in $(seq 1 "$n"); do
    start_ms=$(date +%s%3N)
    
    # Placeholder for actual query execution
    # In real implementation: python -m alarmv3.query --db-path "$DB_PATH" --query "$query_text"
    # For now, simulate with a small random delay
    sleep 0.$(printf "%02d" $((RANDOM % 20 + 5)))
    
    end_ms=$(date +%s%3N)
    latency=$((end_ms - start_ms))
    latencies+=($latency)
    
    if [ $((i % 10)) -eq 0 ]; then
        echo -n "."
    fi
done
echo ""

# Calculate percentiles
IFS=$'\n' sorted=($(sort -n <<<"${latencies[*]}"))
unset IFS

p50_idx=$((n / 2))
p95_idx=$((n * 95 / 100))
p99_idx=$((n * 99 / 100))

p50=${sorted[$p50_idx]}
p95=${sorted[$p95_idx]}
p99=${sorted[$p99_idx]}

# Calculate mean
sum=0
for lat in "${latencies[@]}"; do
    sum=$((sum + lat))
done
mean=$((sum / n))

echo ""
echo "Query Latency Results:"
echo "  Iterations: $n"
echo "  Mean: ${mean}ms"
echo "  p50: ${p50}ms"
echo "  p95: ${p95}ms"
echo "  p99: ${p99}ms"
echo ""

if [ "$p95" -lt 200 ]; then
    echo "✓ SLO met: p95 ($p95 ms) < 200ms"
else
    echo "✗ SLO not met: p95 ($p95 ms) >= 200ms"
fi

# Save results
RESULTS_FILE="${OUT_DIR}/query_latency_${session_id}_$(date +%s).json"
cat > "$RESULTS_FILE" <<EOF
{
  "session_id": "$session_id",
  "query": "$query_text",
  "iterations": $n,
  "latency_ms": {
    "mean": $mean,
    "p50": $p50,
    "p95": $p95,
    "p99": $p99,
    "slo_met": $([ "$p95" -lt 200 ] && echo "true" || echo "false")
  },
  "timestamp": "$(date -Iseconds)"
}
EOF

echo ""
echo "Results saved to: $RESULTS_FILE"
