#!/bin/bash
#
# Echo processor - demonstrates the basic processor contract using bash + jq.
#
# Requires: jq (https://stedolan.github.io/jq/)
#
# Reads JSON Lines from stdin, writes results to stdout.
# Each output must include id, chat_id, and status.

set -e

# Process each line of input
while IFS= read -r line || [[ -n "$line" ]]; do
    # Skip empty lines
    [[ -z "$line" ]] && continue

    # Extract required fields using jq
    msg_id=$(echo "$line" | jq -r '.id // empty')
    chat_id=$(echo "$line" | jq -r '.chat_id // empty')

    # Validate required fields
    if [[ -z "$msg_id" ]] || [[ -z "$chat_id" ]]; then
        # Log error to stderr, output failure
        echo "[ERROR] Missing id or chat_id" >&2
        echo '{"id": 0, "chat_id": 0, "status": "failed"}'
        continue
    fi

    # Optional: extract text for logging
    text=$(echo "$line" | jq -r '.text // empty')
    if [[ -n "$text" ]]; then
        # Log to stderr (truncated to 50 chars)
        echo "[INFO] Processing message $msg_id: ${text:0:50}..." >&2
    fi

    # Your processing logic goes here
    # This example just marks everything as success

    # Output result as JSON
    jq -n \
        --argjson id "$msg_id" \
        --argjson chat_id "$chat_id" \
        '{id: $id, chat_id: $chat_id, status: "success"}'

done