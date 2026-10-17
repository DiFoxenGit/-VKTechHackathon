#!/usr/bin/env bash
# Restrict the dedicated GitHub Actions SSH key to deployment of GitHub main.
set -euo pipefail
read -r command sha rest <<<"${SSH_ORIGINAL_COMMAND:-}"
if [ "$command" != deploy ] || ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || [ -n "$rest" ]; then
    echo 'Expected: deploy <40-character SHA>' >&2
    exit 2
fi
exec flock -w 1800 /root/vk-presentations-main-deploy.lock \
    bash /root/vk-presentations-main/deploy/autosell-deploy.sh "$sha"
