#!/bin/bash
set -euo pipefail

PLIST_SRC="/Users/zhouxiantong/BridgeAI-Harness/agent_team/scripts/com.bridgeai.wiki.weeklyreview.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.bridgeai.wiki.weeklyreview.plist"
LABEL="com.bridgeai.wiki.weeklyreview"

mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
echo "[OK] 已注册每周日 20:00 定时复盘任务：$LABEL"
launchctl list | grep "$LABEL" || true
