"""Private deployment profiles preserve unrelated credentials and reject injection."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'deploy/runtime_profile.py'
spec = importlib.util.spec_from_file_location('runtime_profile', SCRIPT)
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def test_profile_preserves_old_credentials_and_pins_vision_endpoint(tmp_path):
    path = tmp_path / '.env'
    path.write_text('# preserved\nDESIGNER_LLM_API_KEY=old-value\nDESIGNER_LLM_BASE_URL=https://old.invalid/v1\n'
                    'DESIGNER_VLM_MODEL=vision\nDESIGNER_LLM_PROVIDER=openai\nDESIGNER_LLM_PROVIDER=stale\n'
                    'DESIGNER_DATA_DIR=/data\n')
    assert profile.update(path, json.dumps({'DESIGNER_LLM_PROVIDER': 'vk', 'DESIGNER_VK_API_KEY': '$literal'}).encode())
    value = path.read_text()
    assert 'DESIGNER_LLM_API_KEY=old-value\n' in value
    assert 'DESIGNER_VLM_API_KEY=old-value\n' in value
    assert 'DESIGNER_VLM_BASE_URL=https://old.invalid/v1\n' in value
    assert 'DESIGNER_DATA_DIR=/data\n' in value and '# preserved\n' in value
    assert value.count('DESIGNER_LLM_PROVIDER=') == 1
    assert "DESIGNER_VK_API_KEY='$literal'" in value
    assert profile.update(path, json.dumps({'DESIGNER_LLM_PROVIDER': 'vk'}).encode())
    assert path.read_text().count('DESIGNER_VLM_API_KEY=') == 1


@pytest.mark.parametrize('payload', [b'{', b'[]', b'{}', b'x'*65537,
    b'{"DESIGNER_LLM_PROVIDER":"openai"}',
    b'{"DESIGNER_LLM_PROVIDER":"vk","PATH":"/bad"}',
    b'{"DESIGNER_LLM_PROVIDER":"vk","DESIGNER_VK_API_KEY":"oops\\nBAD=1"}',
    b'{"DESIGNER_LLM_PROVIDER":"vk","DESIGNER_MAX_JOBS":2}',
    b'{"DESIGNER_LLM_PROVIDER":"vk","DESIGNER_VK_API_KEY":"bad\'quote"}',
    b'{"DESIGNER_LLM_PROVIDER":"vk","DESIGNER_VK_API_KEY":"bad\\\\slash"}'],
    ids=['malformed', 'array', 'empty', 'oversized', 'wrong-provider', 'unknown-key',
         'newline', 'numeric-value', 'quote', 'backslash'])
def test_invalid_profile_does_not_mutate_env_or_print_secrets(tmp_path, payload):
    path = tmp_path / '.env'
    path.write_bytes(b'EXISTING=preserved\n')
    result = subprocess.run([sys.executable, str(SCRIPT), str(path)], input=payload, capture_output=True, timeout=5)
    assert result.returncode != 0
    assert path.read_bytes() == b'EXISTING=preserved\n'
    assert result.stdout == b''
    assert b'private values omitted' in result.stderr
    assert b'oops' not in result.stderr and b'quote' not in result.stderr


def test_absent_secret_leaves_env_byte_identical(tmp_path):
    path = tmp_path / '.env'
    path.write_bytes(b'KEY = original\r\n')
    assert profile.update(path, b'') is False
    assert path.read_bytes() == b'KEY = original\r\n'


def test_explicit_vision_credentials_are_preserved(tmp_path):
    path = tmp_path / '.env'
    path.write_text('DESIGNER_VLM_MODEL=vision\nDESIGNER_VLM_API_KEY=separate\nDESIGNER_LLM_API_KEY=generic\n')
    profile.update(path, b'{"DESIGNER_LLM_PROVIDER":"vk"}')
    assert 'DESIGNER_VLM_API_KEY=separate\n' in path.read_text()
