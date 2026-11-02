#!/bin/bash
# Daily consumer-trend sentinel (social arbitrage, paper) — headless Claude on the VPS.
# Cron (app): 40 14 * * * /opt/polymarket-insider/scripts/consumer_sentinel.sh
# Records theses via backend.consumer_lane into data/consumer_theses.jsonl
# (dashboard /stocks). Never alerts, never trades.
cd /opt/polymarket-insider || exit 1
mkdir -p /home/app/sentinel
LOG=/home/app/sentinel/consumer_runs.log

TOKEN_FILE=/home/app/.claude/sentinel_oauth_token
if [ -s "$TOKEN_FILE" ]; then
  export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$TOKEN_FILE")"
fi

SIGNALS=$(python3 -I scripts/fetch_consumer.py 2>/dev/null)

OUT=$(claude -p "$(cat scripts/consumer_sentinel.md)

## Pre-fetched consumer signals (today)
$SIGNALS" \
  --model sonnet --max-turns 30 \
  --allowedTools Bash Read Write Edit Glob Grep WebSearch 2>&1)
CODE=$?

{
  echo "=== $(date -u +%FT%TZ) exit=$CODE"
  echo "$OUT" | tail -25
} >> "$LOG"

# Same once-a-day auth warning as the news sentinel (shared stamp file).
if [ $CODE -ne 0 ] && echo "$OUT" | grep -qiE "auth|oauth|login"; then
  STAMP=/home/app/sentinel/.auth_warned
  TODAY=$(date -u +%F)
  if [ "$(cat "$STAMP" 2>/dev/null)" != "$TODAY" ]; then
    python3 scripts/send_telegram.py "⚠️ <b>Consumer-sentinel draait niet</b>: Claude-login op de VPS is verlopen. Fix: <code>ssh -t app@100.102.30.80 claude setup-token</code> → token in /home/app/.claude/sentinel_oauth_token" \
      && echo "$TODAY" > "$STAMP"
  fi
fi
