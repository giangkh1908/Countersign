"""Entrypoint FastAPI của approval_signer: `uvicorn approval_signer.main:app`."""

from acme_common.telemetry import instrument_fastapi

from .api import create_app

app = create_app()
instrument_fastapi(app, "approval-signer")
