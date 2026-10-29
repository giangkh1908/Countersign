"""Spike A: FastMCP 4.1.4 + JWTVerifier (Keycloak), stateless HTTP, tool whoami."""
import os

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token

# JWKS lay qua localhost (host), issuer phai khop CHINH XAC chuoi trong token.
JWKS = os.getenv("JWKS_URI", "http://localhost:8080/realms/acme/protocol/openid-connect/certs")
ISSUER = os.getenv("ISSUER", "http://keycloak.acme.local:8080/realms/acme")

auth = JWTVerifier(jwks_uri=JWKS, issuer=ISSUER, audience="docs-mcp", algorithm="RS256")
mcp = FastMCP("spike-a-docs-mcp", auth=auth)


@mcp.tool
def whoami() -> dict:
    t = get_access_token()
    c = t.claims
    return {"sub": c.get("sub"), "dept": c.get("dept"), "clearance": c.get("clearance"),
            "azp": c.get("azp"), "aud": c.get("aud")}


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=int(os.getenv("PORT", "8911")), stateless_http=True)
