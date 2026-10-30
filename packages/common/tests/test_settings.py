from acme_common.settings import CommonSettings


def test_file_secret_wins_over_env(tmp_path, monkeypatch) -> None:
    f = tmp_path / "metrics"
    f.write_text("from-file\n", encoding="utf8")
    monkeypatch.setenv("METRICS_TOKEN", "from-env")
    monkeypatch.setenv("METRICS_TOKEN_FILE", str(f))
    assert CommonSettings().metrics_token == "from-file"


def test_env_used_without_file(monkeypatch) -> None:
    monkeypatch.delenv("METRICS_TOKEN_FILE", raising=False)
    monkeypatch.setenv("METRICS_TOKEN", "from-env")
    assert CommonSettings().metrics_token == "from-env"


def test_urls_derived_from_issuer_and_overridable(monkeypatch) -> None:
    s = CommonSettings(keycloak_issuer="https://idp.test/realms/r")
    assert s.jwks_url == "https://idp.test/realms/r/protocol/openid-connect/certs"
    assert s.token_url.endswith("/token")
    monkeypatch.setenv("OIDC_JWKS_URL", "http://internal/jwks")
    assert CommonSettings().jwks_url == "http://internal/jwks"


def test_list_settings_parse_comma_separated() -> None:
    s = CommonSettings(token_allowed_azp="agent-service, chat-ui", token_required_claims="sub,dept")
    assert s.allowed_azp == {"agent-service", "chat-ui"}
    assert s.required_claims == ("sub", "dept")


def test_empty_env_value_falls_back_to_default(monkeypatch) -> None:
    # `.env.example` để trống các biến tuỳ chọn (vd `MCP_RL_CAPACITY=`): rỗng = dùng mặc định.
    monkeypatch.setenv("MCP_RL_CAPACITY", "")
    assert (
        CommonSettings().mcp_rl_capacity == CommonSettings.model_fields["mcp_rl_capacity"].default
    )


def test_default_ignored_scopes_cover_login_token_scopes() -> None:
    """Token đăng nhập của chat-ui mang scope `aud-chat-ui` + `acme-claims` (client scope mặc định); khi
    đổi token, Keycloak giữ lại chúng trong claim `scope`. Không được coi là scope_escalation
    (bug phát hiện bởi E2E trình duyệt: mọi /api/* trả 502)."""
    from acme_common.settings import CommonSettings

    ignored = CommonSettings().ignored_scopes
    assert {"openid", "acme-claims", "aud-chat-ui"} <= ignored
