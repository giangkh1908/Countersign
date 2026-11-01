"""Factory của approval_signer: chọn adapter theo config bằng registry dict + lazy import.

Không có adapter `permissive` nào (signer không bao giờ ký "cho qua"). Tên lạ => `XxxNotConfigured`
kèm `sorted(registry)`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from acme_common.factory import lookup
from acme_common.ports import Clock

from .ports import (
    ApprovalSigner,
    ApprovalSignerNotConfigured,
    IntentVerifier,
    IntentVerifierNotConfigured,
)
from .settings import Settings


def _load_es256_jws(settings: Settings, clock: Clock) -> IntentVerifier:
    from .adapters.es256_jws import Es256JwsIntentVerifier

    if not settings.intent_public_keys_dir:
        raise IntentVerifierNotConfigured("INTENT_PUBLIC_KEYS_DIR is required")
    return Es256JwsIntentVerifier(
        settings.intent_public_keys_dir,
        clock,
        issuer=settings.intent_issuer_name,
        audience=settings.signer_audience,
    )


_VERIFIERS: dict[str, Callable[[Settings, Clock], IntentVerifier]] = {"es256_jws": _load_es256_jws}


def build_intent_verifier(name: str, settings: Settings, *, clock: Clock) -> IntentVerifier:
    return lookup(_VERIFIERS, name, IntentVerifierNotConfigured)(settings, clock)


def _load_es256_jwt(settings: Settings, clock: Clock) -> ApprovalSigner:
    from .adapters.es256_jwt import Es256JwtApprovalSigner

    if settings.approval_signer_private_key:
        pem = settings.approval_signer_private_key.encode()
    elif settings.approval_signer_private_key_path:
        pem = Path(settings.approval_signer_private_key_path).read_bytes()
    else:
        raise ApprovalSignerNotConfigured("APPROVAL_SIGNER_PRIVATE_KEY_PATH is required")
    return Es256JwtApprovalSigner(
        pem, settings.approval_signer_key_id or "", clock, ttl_s=settings.approval_ttl_s
    )


_SIGNERS: dict[str, Callable[[Settings, Clock], ApprovalSigner]] = {"es256_jwt": _load_es256_jwt}


def build_approval_signer(name: str, settings: Settings, *, clock: Clock) -> ApprovalSigner:
    return lookup(_SIGNERS, name, ApprovalSignerNotConfigured)(settings, clock)
