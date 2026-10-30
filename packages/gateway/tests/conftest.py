import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gw_support import Env, make_env  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_dotenv(tmp_path, monkeypatch) -> None:
    """`CommonSettings` đọc `.env` theo đường dẫn tương đối; chạy trong thư mục trống."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def env() -> Env:
    return make_env()


@pytest.fixture
async def api_key(env: Env) -> str:
    """Key active, allowed_models = tất cả alias, không tin user token."""
    return await env.new_key()
