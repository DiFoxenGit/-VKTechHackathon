import pytest

from designer import ai


@pytest.fixture(autouse=True)
def _reset_vk_outage():
    # The VK outage window is process-wide; keep tests independent.
    ai._vk_unavailable_until = 0.0
    yield
    ai._vk_unavailable_until = 0.0
