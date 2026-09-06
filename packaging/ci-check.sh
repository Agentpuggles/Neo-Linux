#!/usr/bin/env bash
# Keep normal logs and put a bounded failure tail in the check annotation too.
# This makes failures diagnosable even when a client cannot download log archives.
set -uo pipefail
LOG=$(mktemp)
trap 'rm -f "$LOG"' EXIT
"$@" 2>&1 | tee "$LOG"
status=${PIPESTATUS[0]}
if [[ $status != 0 && ${GITHUB_ACTIONS:-} == true ]]; then
    python3 - "$LOG" <<'PY'
from pathlib import Path
import sys
# GitHub truncates annotation messages to 4096 characters. Keep the *end*
# below that limit so a long PyInstaller log cannot hide its final exception.
# Read only a bounded tail, even if a command generated a very large log.
with Path(sys.argv[1]).open("rb") as stream:
    stream.seek(0, 2)
    stream.seek(max(0, stream.tell() - 32768))
    tail = stream.read()
text = tail[-2800:].decode("utf-8", errors="replace")
text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
print(f"::error title=AppImage check failed::{text}")
PY
fi
exit "$status"
