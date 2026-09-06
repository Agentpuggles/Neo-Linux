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
text = "\n".join(Path(sys.argv[1]).read_text(errors="replace").splitlines()[-80:])[-7000:]
text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
print(f"::error title=AppImage check failed::{text}")
PY
fi
exit "$status"
