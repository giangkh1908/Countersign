"""Nạp harness dùng chung (importlib mode không tự thêm thư mục test vào sys.path)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bff_harness import _isolate_dotenv, env, logged_in  # noqa: E402,F401
