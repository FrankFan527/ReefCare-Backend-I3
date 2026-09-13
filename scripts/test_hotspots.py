"""Run offline API/unit regression tests with explicit dummy service settings.

Usage: python scripts/test_hotspots.py
No Neon or Supabase connection is made. Run live integration tests separately.
"""

import os
from pathlib import Path
import sys

import pytest


root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root))
os.environ.update(
    APP_ENV="test",
    DATABASE_URL="postgresql+psycopg://test:test@127.0.0.1:5432/reefcare_test",
    JWT_SECRET_KEY="offline-test-secret-only-01234567890123456789",
    SUPABASE_URL="https://example.supabase.co",
    SUPABASE_SECRET_KEY="offline-test-placeholder",
    HOTSPOT_ENABLED="true",
    HOTSPOT_MAP_CONFIG="config/hotspot-sites.json",
    HOTSPOT_TIMEOUT_SECONDS="10",
)
raise SystemExit(pytest.main(["tests", "-m", "not integration", "-q", *sys.argv[1:]]))
