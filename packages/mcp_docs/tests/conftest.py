from __future__ import annotations

import asyncio
import sys

import pytest

if sys.platform == "win32":  # psycopg async không chạy trên ProactorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(autouse=True)
def _isolate_dotenv(tmp_path, monkeypatch) -> None:
    """`Settings` đọc `.env` theo đường dẫn tương đối: chạy trong thư mục trống."""
    monkeypatch.chdir(tmp_path)
