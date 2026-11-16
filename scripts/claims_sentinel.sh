#!/bin/bash
# Insider-claim sentinel (paper) — headless Claude on the VPS, every 6h.
# Cron (app): 10 */6 * * * /opt/polymarket-insider/scripts/claims_sentinel.sh
# Reads news / X (Firecrawl) / EventWaves, adds named wallets to the paper
# sharp-wallet follower (data/sharp_wallets.json) and journals claims in
# /home/app/sentinel/claims_journal.jsonl. Never trades, never alerts.
cd /opt/polymarket-insider || exit 1
mkdir -p /home/app/sentinel
LOG=/home/app/sentinel/claims_runs.log

ITEMS=$(python3 -I scripts/fetch_insider_claims.py 2>&1)
N=$(echo "$ITEMS" | python3 -c "import json,sys; print(json.load(sys.stdin).get('n_new',0))" 2>/dev/null || echo 0)
if [ "$N" = "0" ]; then
  echo "=== $(date -u +%FT%TZ) no new items" >> "$LOG"
  exit 0
fi

TOKEN_FILE=/home/app/.claude/sentinel_oauth_token
if [ -s "$TOKEN_FILE" ]; then
  export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$TOKEN_FILE")"
fi

OUT=$(claude -p "$(cat scripts/claims_sentinel.md)

## Pre-fetched new items ($N)
$ITEMS" \
  --model sonnet --max-turns 30 \
  --allowedTools Bash Read WebFetch WebSearch 2>&1)
CODE=$?

{
  echo "=== $(date -u +%FT%TZ) exit=$CODE items=$N"
  echo "$OUT" | tail -20
} >> "$LOG"

# Same once-a-day auth warning as the other sentinels (shared stamp file).
if [ $CODE -ne 0 ] && echo "$OUT" | grep -qiE "auth|oauth|login"; then
  STAMP=/home/app/sentinel/.auth_warned
  TODAY=$(date -u +%F)
  if [ "$(cat "$STAMP" 2>/dev/null)" != "$TODAY" ]; then
    python3 scripts/send_telegram.py "⚠️ <b>Claims-sentinel draait niet</b>: Claude-login op de VPS is verlopen. Fix: <code>ssh -t app@100.102.30.80 claude setup-token</code> → token in /home/app/.claude/sentinel_oauth_token" \
      && echo "$TODAY" > "$STAMP"
  fi
fi
