import pytest


@pytest.fixture(autouse=True)
def _isolate_dotenv(tmp_path, monkeypatch) -> None:
    """`CommonSettings` đọc `.env` theo đường dẫn tương đối; chạy test trong thư mục trống
    để `.env` thật ở gốc repo không lọt vào test."""
    monkeypatch.chdir(tmp_path)
