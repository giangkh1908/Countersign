import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # --import-mode=importlib không tự thêm


@pytest.fixture(autouse=True)
def _isolate_dotenv(tmp_path, monkeypatch) -> None:
    """`Settings` đọc `.env` theo đường dẫn tương đối; chạy test trong thư mục trống."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(scope="module")
def event_loop_policy():
    """psycopg async không chạy trên ProactorEventLoop (Windows)."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()
