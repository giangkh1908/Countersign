"""approval-signer toi thieu: nhan token (b) aud=approval-signer, ky approval JWS ES256."""
import hashlib, json, time, uuid
import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jwt.algorithms import ECAlgorithm
import common

# Khoa tam sinh luc khoi dong (KHONG dung secrets/*.pem)
_KEY = ec.generate_private_key(ec.SECP256R1())
KID = "spike-b-" + uuid.uuid4().hex[:8]
JWK = json.loads(ECAlgorithm.to_jwk(_KEY.public_key()))
JWK.update(kid=KID, use="sig", alg="ES256")

app = FastAPI()


def intent_sha256(intent: dict) -> str:
    return hashlib.sha256(json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def err(status, error, detail):
    return JSONResponse({"error": error, "detail": detail}, status_code=status)


@app.get("/v1/jwks")
def jwks():
    return {"keys": [JWK]}


@app.post("/v1/approvals")
async def approvals(req: Request):
    h = req.headers.get("authorization", "")
    if not h.lower().startswith("bearer "):
        return err(401, "unauthenticated", "missing bearer")
    try:
        c = common.verify_kc_token(h[7:])
    except Exception as e:
        return err(401, "invalid_token", f"{type(e).__name__}: {e}")
    if "approval-signer" not in common.aud_list(c):
        return err(401, "invalid_audience", f"aud={c.get('aud')} khong chua approval-signer")
    if c.get("azp") != "chat-ui":
        return err(403, "invalid_azp", f"azp={c.get('azp')} != chat-ui")
    body = await req.json()
    intent, decision = body.get("intent") or {}, body.get("decision")
    if decision not in ("approve", "reject"):
        return err(400, "bad_decision", str(decision))
    if intent.get("sub") != c.get("sub"):
        return err(403, "sub_mismatch", "token.sub != intent.sub")
    now = int(time.time())
    claims = {"iss": "approval-signer", "sub": c["sub"], "intent_id": intent.get("intent_id"),
              "intent_sha256": intent_sha256(intent), "decision": decision, "jti": uuid.uuid4().hex,
              "iat": now, "exp": now + 300}
    return {"approval_jws": jwt.encode(claims, _KEY, algorithm="ES256", headers={"kid": KID})}
