"""Entrypoint FastAPI của approval_signer: `uvicorn approval_signer.main:app`."""

from .api.app import create_app

app = create_app()
