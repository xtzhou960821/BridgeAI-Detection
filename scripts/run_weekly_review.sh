#!/bin/bash
set -euo pipefail

TEAM_DIR="/Users/zhouxiantong/BridgeAI-Harness/agent_team"
DIGEST_FILE="$TEAM_DIR/logs/weekly_digest.md"

mkdir -p "$TEAM_DIR/logs"
{
  echo "# Weekly Agent Team Review ($(date '+%Y-%m-%d %H:%M:%S'))"
  echo ""
  "$TEAM_DIR/.venv/bin/python" "$TEAM_DIR/weekly_review.py"
} > "$DIGEST_FILE"
