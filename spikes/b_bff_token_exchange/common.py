"""Tien ich dung chung cho Spike B (khong phai code san xuat)."""
import base64, json, os, re
from pathlib import Path
from urllib.parse import urlencode
import httpx, jwt
from jwt import PyJWKClient

SECRETS = Path(os.environ.get("SPIKE_B_SECRETS", r"D:\AI_EXAMPLE\secrets"))
KC_INTERNAL = os.environ.get("SPIKE_B_KC_INTERNAL", "http://localhost:8080/realms/acme")  # server->server
KC_PUBLIC = os.environ.get("SPIKE_B_KC_PUBLIC", "http://keycloak.acme.local:8080/realms/acme")  # trinh duyet thay + claim iss
ISSUER = KC_PUBLIC
TOKEN_URL = f"{KC_INTERNAL}/protocol/openid-connect/token"
JWKS_URL = f"{KC_INTERNAL}/protocol/openid-connect/certs"
JWT_RE = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]*")

_jwks = PyJWKClient(JWKS_URL, cache_keys=True)


def secret(name: str) -> str:
    return (SECRETS / name).read_text(encoding="utf8").strip()


def claims_unverified(t: str) -> dict:
    p = t.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


def verify_kc_token(t: str) -> dict:
    """Chu ky (JWKS Keycloak), iss, exp. Kiem aud/azp do ben goi tu lam."""
    key = _jwks.get_signing_key_from_jwt(t).key
    return jwt.decode(t, key, algorithms=["RS256"], issuer=ISSUER,
                      options={"verify_aud": False, "require": ["exp", "iss"]})


def aud_list(c: dict) -> list:
    a = c.get("aud", [])
    return [a] if isinstance(a, str) else list(a)


def exchange(client_id, client_secret, subject_token, audience=None, scope=None, extra=None):
    """RFC 8693 qua Keycloak. audience co the la str hoac list. Tra (status, json)."""
    data = [("grant_type", "urn:ietf:params:oauth:grant-type:token-exchange"),
            ("subject_token", subject_token),
            ("subject_token_type", "urn:ietf:params:oauth:token-type:access_token"),
            ("requested_token_type", "urn:ietf:params:oauth:token-type:access_token"),
            ("client_id", client_id), ("client_secret", client_secret)]
    for a in ([audience] if isinstance(audience, str) else (audience or [])):
        data.append(("audience", a))
    if scope:
        data.append(("scope", scope))
    data += list((extra or {}).items())
    r = httpx.post(TOKEN_URL, content=urlencode(data), headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text[:200]}


def show_claims(c: dict) -> dict:
    keys = ("aud", "azp", "scope", "sub", "dept", "clearance", "act", "may_act", "sid", "typ")
    d = {k: (c.get(k) if k in c else "<absent>") for k in keys}
    d["exp-iat"] = c["exp"] - c["iat"]
    return d


def redact(t: str) -> str:
    h, p, _ = t.split(".")
    return f"{h[:12]}.{p[:12]}...<sig>"
