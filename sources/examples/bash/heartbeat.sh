#!/bin/bash
# Heartbeat source - demonstrates the source protocol in Bash.
# Uses: sleep for scheduling, shell date command for timestamps.
#
# CORE CONVENTIONS (follow these when developing your own sources):
# 1. File naming: incoming.YYYY-MM-DD.jsonl (day-level, not seconds)
# 2. Date monotonicity: Always write to today's file (recalculate date each time)
# 3. Append-only: Only append (>>), never overwrite (>)
# 4. Atomic writes: Optional but recommended (temp file + rename)
#
# Environment variables:
#     TELE_SOURCE_PATH - Directory for incoming files (default: ~/.tele/state/sources/heartbeat)
#     TELE_CHAT_ID     - Target chat ID for messages (default: 0)
#     TELE_INTERVAL    - Seconds between heartbeats (default: 60)

set -e

# Configuration from environment
SOURCE_PATH="${TELE_SOURCE_PATH:-~/.tele/state/sources/heartbeat}"
CHAT_ID="${TELE_CHAT_ID:-0}"
INTERVAL="${TELE_INTERVAL:-60}"
SOURCE_NAME="heartbeat"

# Expand ~ in SOURCE_PATH
SOURCE_PATH=$(eval echo "$SOURCE_PATH")

# Ensure directory exists
mkdir -p "$SOURCE_PATH"

echo "[INFO] Starting heartbeat source"
echo "[INFO] Path: $SOURCE_PATH"
echo "[INFO] Chat ID: $CHAT_ID"
echo "[INFO] Interval: $INTERVAL seconds"

# Main loop
while true; do
    # CORE CONVENTION #1 & #2: Recalculate date each iteration
    # This handles midnight transition - date naturally advances
    DATE=$(date +%Y-%m-%d)
    FILE="$SOURCE_PATH/incoming.$DATE.jsonl"

    # Generate timestamp for message content
    TIMESTAMP=$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S)

    # Generate unique ID (using $RANDOM and timestamp)
    ID="heartbeat-$RANDOM-$TIMESTAMP"

    # Build JSON message
    # Using printf to avoid shell escaping issues
    MSG=$(printf '{"id":"%s","chat_id":%s,"text":"Heartbeat at %s","date":"%s","source":"%s"}' \
        "$ID" "$CHAT_ID" "$TIMESTAMP" "$TIMESTAMP" "$SOURCE_NAME")

    # CORE CONVENTION #3: Append mode (>>), NEVER overwrite (>)
    # This ensures files are audit logs, not replaced
    echo "$MSG" >> "$FILE"

    # Log to stderr (stdout not used in sources)
    echo "[INFO] Wrote heartbeat to incoming.$DATE.jsonl"

    # Wait for next iteration
    # Date will be recalculated after sleep, handling midnight
    sleep "$INTERVAL"
done