#!/bin/bash
# Copy derived data (never published) to the server and reload it.
# Usage: scripts/push-data.sh [user@host]
set -euo pipefail
HOST=${1:-pavel@192.168.0.113}
cd "$(dirname "$0")/.."
cp data/text/chunks.jsonl data/derived/chunks.jsonl
scp data/derived/{vectors.jsonl,chunks.jsonl,lore_bible.md,dialogue.jsonl} "$HOST:/opt/tendruhy/data/derived/"
ssh "$HOST" 'cd /opt/tendruhy && docker compose exec -T tendruhy python -m ingest.embed --load && docker compose restart tendruhy'
