"""
Apex Scout - Pytest Configuration
"""

import pytest
import sys
from pathlib import Path

# Proje kökünü path'e ekle
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="session")
def event_loop():
    """Asyncio event loop for session"""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def reset_singletons():
    """Test arası singleton'ları temizle"""
    # Config settings reset (eğer gerekirse)
    yield
    # Cleanup after test