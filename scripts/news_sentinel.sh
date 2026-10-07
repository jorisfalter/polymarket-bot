#!/bin/bash
# Hourly news sentinel — headless Claude Code on the VPS (subscription auth, app user).
# Cron (app): 20 * * * * /opt/polymarket-insider/scripts/news_sentinel.sh
cd /opt/polymarket-insider || exit 1
mkdir -p /home/app/sentinel
LOG=/home/app/sentinel/runs.log

# Long-lived headless auth (claude setup-token, ~1 yr) instead of the
# interactive OAuth session that expires every few weeks. Token file is
# app-only (600), never in git.
TOKEN_FILE=/home/app/.claude/sentinel_oauth_token
if [ -s "$TOKEN_FILE" ]; then
  export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$TOKEN_FILE")"
fi

# Pre-fetch headlines here so the model doesn't spend a tool turn on it.
NEWS=$(python3 scripts/fetch_news.py 2>/dev/null)

OUT=$(claude -p "$(cat scripts/sentinel.md)

## Pre-fetched headlines (this hour)
$NEWS" \
  --model sonnet --max-turns 20 \
  --allowedTools Bash Read Write Edit Glob Grep WebSearch WebFetch 2>&1)
CODE=$?

{
  echo "=== $(date -u +%FT%TZ) exit=$CODE"
  echo "$OUT" | tail -25
} >> "$LOG"

# Auth expired -> warn via Telegram, at most once per day.
if [ $CODE -ne 0 ] && echo "$OUT" | grep -qiE "auth|oauth|login"; then
  STAMP=/home/app/sentinel/.auth_warned
  TODAY=$(date -u +%F)
  if [ "$(cat "$STAMP" 2>/dev/null)" != "$TODAY" ]; then
    python3 scripts/send_telegram.py "⚠️ <b>News-sentinel draait niet</b>: Claude-login op de VPS is verlopen. Fix: <code>ssh -t app@100.102.30.80 claude setup-token</code> → token in /home/app/.claude/sentinel_oauth_token" \
      && echo "$TODAY" > "$STAMP"
  fi
fi
