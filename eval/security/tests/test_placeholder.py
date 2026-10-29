import pytest


@pytest.mark.skip(reason="M5: security regression R1-R8 chưa triển khai")
def test_security_regression_placeholder() -> None:
    raise AssertionError
