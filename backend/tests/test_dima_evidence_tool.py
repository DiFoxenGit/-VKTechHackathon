"""An explicit live flag, bounded cases and factual audit restoration."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from check_dima_editorial import audit_fixture, require_vk


def test_audit_fixture_preserves_protected_blocks_after_semantic_fix():
    fixture = audit_fixture()
    assert fixture['synthetic_defective_copy'] and fixture['protected_facts_unchanged']
    assert fixture['protected_before_sha256'] == fixture['protected_after_sha256']
    assert fixture['after_semantic_fix'] == fixture['original']
    assert fixture['defective']['title'] != fixture['original']['title']


def test_provider_at_envelope_level_is_valid_but_fallback_is_not_vk_acceptance():
    trace = dict(completed=True, validation='passed', fallback_used=False, provider='vk',
        model='qwen38-27b-fp8', successful_calls=1, calls=[dict(provider=None, status_code=200)])
    require_vk(trace)
    for field, value in [('fallback_used', True), ('provider', 'genapi'), ('model', 'other')]:
        changed = copy.deepcopy(trace)
        changed[field] = value
        with pytest.raises(ValueError):
            require_vk(changed)
