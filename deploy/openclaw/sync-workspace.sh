#!/usr/bin/env bash
# Run as your admin user (not claw) after `git -C /opt/jobapply pull`: rebuilds the read-only venv the agent
# runs `jobs` from, and refreshes the agent's read-only copies of AGENTS.md and KNOWLEDGE.md.
set -euo pipefail

CODE=/opt/jobapply
WS=/home/claw/jobapply-home

# Python and the venv must live where claw can read them (not in your home directory).
export UV_PYTHON_INSTALL_DIR=/opt/uv-python UV_LINK_MODE=copy
cd "$CODE"
uv sync --frozen --no-dev
chmod -R a+rX "$CODE" /opt/uv-python

for f in AGENTS.md KNOWLEDGE.md; do
  sudo chattr -i "$WS/$f" 2>/dev/null || true
  sudo install -o root -g root -m 0444 "$CODE/$f" "$WS/$f"
  sudo chattr +i "$WS/$f"   # claw owns the workspace, so only the immutable flag stops it replacing these
done

echo "Done. Now, as claw: systemctl --user restart openclaw-gateway.service"
