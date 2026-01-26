#!/usr/bin/env bash
# Usage: ./scripts/run_index_and_log.sh /path/to/app ./out
set -euo pipefail

APP_PATH="${1:-/tmp/demo_app}"
OUT_DIR="${2:-./out}"
SESSION_NAME="pilot_$(date +%s)"

echo "Starting indexing pipeline..."
echo "  App path: $APP_PATH"
echo "  Output dir: $OUT_DIR"
echo "  Session: $SESSION_NAME"

# Create output directory
mkdir -p "$OUT_DIR"

# Log file
LOG_FILE="$OUT_DIR/index_${SESSION_NAME}.log"

echo "Logging to: $LOG_FILE"
echo ""

# Record start time
START_TIME=$(date +%s)
echo "[$(date -Iseconds)] Starting indexing for session: $SESSION_NAME" | tee -a "$LOG_FILE"

# Check if app path exists
if [ ! -d "$APP_PATH" ]; then
    echo "ERROR: App path does not exist: $APP_PATH" | tee -a "$LOG_FILE"
    exit 1
fi

# Count files in app
FILE_COUNT=$(find "$APP_PATH" -type f \( -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.java" -o -name "*.go" \) | wc -l)
echo "[$(date -Iseconds)] Found $FILE_COUNT code files in $APP_PATH" | tee -a "$LOG_FILE"

# Placeholder for actual indexing command
# In a real implementation, this would call the ALARMv3 indexing pipeline
echo "[$(date -Iseconds)] Indexing would run here (placeholder)" | tee -a "$LOG_FILE"
echo "[$(date -Iseconds)] Example: python -m alarmv3.index --app-path $APP_PATH --db-path $OUT_DIR/rag_db --session $SESSION_NAME" | tee -a "$LOG_FILE"

# Simulate indexing with a sleep
echo "[$(date -Iseconds)] Running indexing pipeline..." | tee -a "$LOG_FILE"
sleep 2

# Record completion
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Generate summary (placeholder values for demo)
CHUNK_COUNT=$((FILE_COUNT * 5))  # Estimate: 5 chunks per file
echo "[$(date -Iseconds)] Indexed $CHUNK_COUNT code chunks in $DURATION seconds" | tee -a "$LOG_FILE"
echo "[$(date -Iseconds)] Vector DB saved to: $OUT_DIR/rag_db" | tee -a "$LOG_FILE"
echo "[$(date -Iseconds)] Session ID: $SESSION_NAME" | tee -a "$LOG_FILE"

# Create session info file
SESSION_FILE="$OUT_DIR/session_${SESSION_NAME}.json"
cat > "$SESSION_FILE" <<EOF
{
  "session_id": "$SESSION_NAME",
  "app_path": "$APP_PATH",
  "db_path": "$OUT_DIR/rag_db",
  "start_time": $START_TIME,
  "end_time": $END_TIME,
  "duration_sec": $DURATION,
  "file_count": $FILE_COUNT,
  "chunk_count": $CHUNK_COUNT,
  "log_file": "$LOG_FILE"
}
EOF

echo ""
echo "✓ Indexing complete!"
echo "  Duration: ${DURATION}s"
echo "  Chunks: $CHUNK_COUNT"
echo "  Session file: $SESSION_FILE"
echo "  Log file: $LOG_FILE"
