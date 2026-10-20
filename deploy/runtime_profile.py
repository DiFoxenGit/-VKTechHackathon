"""Apply the CI secret allowlist to a private dotenv file; never print values."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ALLOWED = {
    'DESIGNER_LLM_PROVIDER', 'DESIGNER_MAX_JOBS',
    'DESIGNER_VK_BASE_URL', 'DESIGNER_VK_MODEL', 'DESIGNER_VK_API_KEY',
    'DESIGNER_VK_PROJECT_ID', 'DESIGNER_VK_TIMEOUT', 'DESIGNER_VK_MAX_TOKENS',
    'DESIGNER_VK_JSON_MODE', 'DESIGNER_VK_SKIP',
    'DESIGNER_FALLBACK_PROVIDER', 'DESIGNER_FALLBACK_MODEL', 'DESIGNER_FALLBACK_API_KEY',
    'DESIGNER_FALLBACK_MAX_TOKENS', 'DESIGNER_FALLBACK_TIMEOUT',
    'DESIGNER_IMAGE_PROVIDER', 'DESIGNER_IMAGE_MODEL', 'DESIGNER_IMAGE_API_KEY',
    'DESIGNER_IMAGE_SIZE', 'DESIGNER_IMAGE_LIMIT',
}


def update(path, payload):
    if not payload.strip():
        return False
    if len(payload) > 65536:
        raise ValueError('Invalid runtime profile')
    profile = json.loads(payload)
    if not isinstance(profile, dict) or not profile or profile.keys() - ALLOWED:
        raise ValueError('Invalid runtime profile')
    if any(not isinstance(value, str) or len(value) > 8192 or "'" in value or '\\' in value or
           any(ord(char) < 32 or ord(char) == 127 for char in value) for value in profile.values()):
        raise ValueError('Invalid runtime profile')
    # Explicit profile only; changing unrelated backend settings is not supported.
    if profile.get('DESIGNER_LLM_PROVIDER') != 'vk':
        raise ValueError('Invalid runtime profile')
    lines = path.read_text(encoding='utf-8').splitlines()
    assignment = re.compile(r'^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=(.*)$')
    old = {m[1]: m[2] for line in lines if (m := assignment.match(line))}
    # Preserve a separately configured vision model's old generic endpoint/key.
    pinned = {}
    if old.get('DESIGNER_VLM_MODEL', '').strip().strip('\'"'):
        for suffix in ('BASE_URL', 'API_KEY'):
            key = 'DESIGNER_VLM_' + suffix
            if not old.get(key, '').strip().strip('\'"') and 'DESIGNER_LLM_' + suffix in old:
                pinned[key] = old['DESIGNER_LLM_' + suffix]
    replacing = profile.keys() | pinned.keys()
    kept = [line for line in lines if not ((m := assignment.match(line)) and m[1] in replacing)]
    for key, value in sorted(profile.items()):
        # Single-quoted dotenv prevents Compose interpolation of dollar signs.
        kept.append(key + "='" + value + "'")
    kept.extend(key + '=' + value for key, value in sorted(pinned.items()))
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file:
            file.write('\n'.join(kept) + '\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return True


if __name__ == '__main__':
    try:
        changed = update(Path(sys.argv[1]), sys.stdin.buffer.read(65537))
    except (ValueError, OSError, IndexError):
        raise SystemExit('Runtime profile rejected; private values omitted') from None
    print('Runtime profile applied' if changed else 'Existing runtime profile preserved')
