def test_import_and_settings() -> None:
    import acme_common
    from acme_common.settings import CommonSettings

    assert acme_common is not None
    assert CommonSettings().acme_env in {"dev", "test", "bench", "eval"}
