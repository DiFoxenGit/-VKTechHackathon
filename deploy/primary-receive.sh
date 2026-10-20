#!/usr/bin/env bash
# Installed outside the checkout; the dedicated CI key cannot open a shell.
set -euo pipefail
if ! [[ "${SSH_ORIGINAL_COMMAND:-}" =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
    echo 'Expected: deploy <40-character SHA>' >&2
    exit 2
fi
sha="${BASH_REMATCH[1]}"
exec flock -w 1800 /home/administrator/vk-designer-runtime/primary-deploy.lock \
    bash /home/administrator/vk-designer-runtime/primary-deploy.sh "$sha"
