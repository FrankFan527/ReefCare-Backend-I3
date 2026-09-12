# ---------------------------------------------------------------------------
# Shared pytest configuration.
#
# Applies to every test in this directory and below, which is why it is kept
# to environment setup only. Fixtures shared by one group of tests belong in a
# conftest.py beside those tests rather than here.
# ---------------------------------------------------------------------------

import asyncio
import sys


# psycopg's async driver cannot run on the ProactorEventLoop, which is what
# Windows uses by default from Python 3.8 onwards. Without this, every
# integration test that opens a database connection fails before it reaches
# any application code, with an InterfaceError that looks like a driver
# problem rather than an environment one.
#
# Set at import time rather than in a fixture, because the policy has to be in
# place before pytest-asyncio creates its first event loop.
#
# The guard matters: SelectorEventLoop is already the default on Linux and
# macOS, and WindowsSelectorEventLoopPolicy does not exist there, so an
# unguarded call would break the suite for everyone not on Windows — including
# whatever runs it in CI.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )