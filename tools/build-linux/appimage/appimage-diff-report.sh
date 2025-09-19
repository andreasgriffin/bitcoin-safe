#!/usr/bin/env bash
# appimage-diff-report.sh
# Compare two AppImages and pinpoint why their hashes differ.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: appimage-diff-report.sh [--keep] [--work DIR] A.AppImage B.AppImage

Options:
  -k, --keep        Keep the temporary workspace folder after the script finishes.
      --work DIR    Use (and keep) a specific workspace directory instead of mktemp.
  -h, --help        Show this help.

Examples:
  appimage-diff-report.sh local.AppImage cloud.AppImage
  appimage-diff-report.sh --keep local.AppImage cloud.AppImage
  appimage-diff-report.sh --work ./_appimg_diff local.AppImage cloud.AppImage
EOF
}

# ---------- parse flags ----------
KEEP=0
CUSTOM_WORK=""
while [[ $# -gt 0 ]]; do
  case "${1:-}" in
    -k|--keep) KEEP=1; shift ;;
    --work)    CUSTOM_WORK="${2:?--work needs a directory}"; KEEP=1; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    --)        shift; break ;;
    -* ) echo "Unknown option: $1" >&2; usage; exit 2 ;;
    * ) break ;;
  esac
done

A="${1:?path to first AppImage missing}"
B="${2:?path to second AppImage missing}"

have() { command -v "$1" >/dev/null 2>&1; }

# ---------- choose hash command (system binary) ----------
if have sha256sum; then
  HASHCMD=(sha256sum)
else
  HASHCMD=(shasum -a 256)
fi

# ---------- helpers ----------
find_offset() {
  local f="$1"
  # Preferred: ask the AppImage itself (type-2 AppImages)
  if chmod +x "$f" 2>/dev/null && "$f" --appimage-offset >/dev/null 2>&1; then
    "$f" --appimage-offset
    return 0
  fi
  # Fallback: search for SquashFS magic ("hsqs")
  if have grep; then
    local off
    off="$(grep -abo -m1 'hsqs' -- "$f" | cut -d: -f1 || true)"
    if [[ -n "${off:-}" ]]; then printf '%s\n' "$off"; return 0; fi
  fi
  echo "ERROR: Could not determine SquashFS offset for $f" >&2
  return 1
}

# ---------- workspace ----------
if [[ -n "$CUSTOM_WORK" ]]; then
  work="$CUSTOM_WORK"
  mkdir -p "$work"
else
  work="$(mktemp -d 2>/dev/null || mktemp -d -t appimgdiff)"
fi

cleanup() {
  if [[ "$KEEP" -eq 0 && -z "$CUSTOM_WORK" ]]; then
    rm -rf "$work"
  else
    echo "Keeping workspace at: $work"
  fi
}
trap cleanup EXIT

echo "Workspace: $work"
echo

oa="$(find_offset "$A")"
ob="$(find_offset "$B")"

echo "== OFFSETS =="
echo "A offset: $oa"
echo "B offset: $ob"
echo

# ---------- split runtime vs squashfs (fast; no bs=1) ----------
# runtime: first $offset bytes
head -c "$oa" -- "$A" > "$work/A.runtime"
head -c "$ob" -- "$B" > "$work/B.runtime"

# squashfs: everything starting at byte $offset (0-based)
startA=$((oa+1))
startB=$((ob+1))
tail -c +$startA -- "$A" > "$work/A.squashfs"
tail -c +$startB -- "$B" > "$work/B.squashfs"

echo "== SHA256 =="
"${HASHCMD[@]}" "$work/A.runtime" "$work/B.runtime" "$work/A.squashfs" "$work/B.squashfs"
echo

echo "== RUNTIME BYTES (first differences) =="
if have cmp; then
  cmp -l "$work/A.runtime" "$work/B.runtime" | head -n 10 || true
else
  echo "cmp: not available"
fi
echo

if have unsquashfs; then
  echo "== SQUASHFS SUPERBLOCKS =="
  unsquashfs -s "$work/A.squashfs" || true
  unsquashfs -s "$work/B.squashfs" || true
  echo

  echo "== LISTINGS WITH MTIMES/PERMS =="
  unsquashfs -ll "$work/A.squashfs" > "$work/A.list"
  unsquashfs -ll "$work/B.squashfs" > "$work/B.list"
  diff -u "$work/A.list" "$work/B.list" | head -n 80 || true
  echo

  echo "== EXTRACT + PER-FILE HASHES =="
  unsquashfs -d "$work/Aroot" "$work/A.squashfs" >/dev/null
  unsquashfs -d "$work/Broot" "$work/B.squashfs" >/dev/null

  # Hash each file in stable (sorted) path order
  (
    cd "$work/Aroot"
    find . -type f -print0 | sort -z | xargs -0 -n1 -- "${HASHCMD[@]}"
  ) > "$work/A.filesums"

  (
    cd "$work/Broot"
    find . -type f -print0 | sort -z | xargs -0 -n1 -- "${HASHCMD[@]}"
  ) > "$work/B.filesums"

  diff -u "$work/A.filesums" "$work/B.filesums" | head -n 80 || true
  echo
else
  echo "(!) 'unsquashfs' not found; skipping SquashFS metadata/content checks."
  echo
fi

echo "== UPDATE INFO / SIGNATURE (if present) =="
{ "$A" --appimage-updateinformation 2>/dev/null || true; } | sed 's/^/A update info: /' || true
{ "$B" --appimage-updateinformation 2>/dev/null || true; } | sed 's/^/B update info: /' || true
echo "A signature:"; { "$A" --appimage-signature 2>/dev/null | head -n 5; } || true
echo "B signature:"; { "$B" --appimage-signature 2>/dev/null | head -n 5; } || true
echo
