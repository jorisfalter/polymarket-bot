#!/bin/bash
# Host cron (as app): snapshot subreddit listings with `sudo reddit-read` into data/reddit/,
# because the container cannot call reddit-read and reddit.com/.json returns 403 from the VPS.
# backend/reddit_data.py reads these files (same Listing JSON).
set -u
OUT=/opt/polymarket-insider/data/reddit
mkdir -p "$OUT"
snap() {  # sub sort limit
  local f="$OUT/${1}_${2}.json"
  sudo -n reddit-read "$1" "$2" --limit "$3" --json > "$f.tmp" 2>/dev/null && [ -s "$f.tmp" ] && mv "$f.tmp" "$f" || rm -f "$f.tmp"
}
snap wallstreetbets hot 50
snap wallstreetbets new 50
for s in $(cd /opt/polymarket-insider && python3 -c "import re;t=open('backend/reddit_data.py').read();b=t[t.index('RESEARCH_SUBREDDITS = ['):];print(' '.join(re.findall(r'\"(\w+)\"',b[:b.index(']')])))"); do
  [ "$s" = wallstreetbets ] && continue
  snap "$s" hot 30
done
