#!/bin/sh
# Daily Paper - KUAL action script.
# Usage: dailypaper.sh fetch | show | screensaver

BASE="$(cd "$(dirname "$0")/.." && pwd)"
. "$BASE/settings.conf"

DATA="/mnt/us/dailypaper"
IMG="$DATA/paper.png"
TMP="$DATA/paper.tmp"
LOG="$DATA/log.txt"
SAVER_DIR="/mnt/us/linkss/screensavers"   # used by the screensaver hack if installed
mkdir -p "$DATA"

say() { eips 2 2 "$1" >/dev/null 2>&1; echo "$(date '+%F %T') $1" >> "$LOG"; }

wifi_up() {
  lipc-set-prop com.lab126.cmd wirelessEnable 1 >/dev/null 2>&1
  i=0
  while [ $i -lt 40 ]; do
    st="$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null)"
    [ "$st" = "CONNECTED" ] && return 0
    sleep 1
    i=$((i + 1))
  done
  return 1
}

download() {
  rm -f "$TMP"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --max-time 60 -o "$TMP" "$PAPER_URL" 2>>"$LOG" && return 0
    # some firmware lacks up-to-date CA certs
    curl -fsSLk --max-time 60 -o "$TMP" "$PAPER_URL" 2>>"$LOG" && return 0
  fi
  wget -q -T 60 -O "$TMP" "$PAPER_URL" 2>>"$LOG" && return 0
  wget -q --no-check-certificate -T 60 -O "$TMP" "$PAPER_URL" 2>>"$LOG" && return 0
  return 1
}

show() {
  if [ ! -s "$IMG" ]; then
    say "No paper downloaded yet."
    return 1
  fi
  eips -c >/dev/null 2>&1
  eips -f -g "$IMG" >/dev/null 2>&1
}

fetch() {
  say "Daily Paper: connecting to Wi-Fi..."
  if ! wifi_up; then
    say "No Wi-Fi connection. Showing last paper."
    sleep 2
    show
    return 1
  fi
  say "Downloading today's paper..."
  if download && [ "$(wc -c < "$TMP")" -gt 5000 ]; then
    mv "$TMP" "$IMG"
    return 0
  fi
  rm -f "$TMP"
  say "Download failed. Check PAPER_URL. Showing last paper."
  sleep 2
  show
  return 1
}

case "$1" in
  fetch)
    fetch && show
    ;;
  show)
    show
    ;;
  screensaver)
    if fetch; then
      if [ -d "$SAVER_DIR" ]; then
        cp "$IMG" "$SAVER_DIR/bg_dailypaper.png"
        say "Saved as screensaver. Done."
      else
        say "Screensaver hack not found ($SAVER_DIR)."
      fi
    fi
    ;;
  *)
    say "Unknown action: $1"
    ;;
esac
