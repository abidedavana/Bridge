"""The dashboard FastAPI app: serves one static page and one JSON endpoint.

`GET /api/state` returns the current run-state JSON (or `{"status": "NO_RUN"}`
before any run). `GET /` serves the single-page UI, which polls `/api/state`.
FastAPI/uvicorn are optional dependencies (`pip install 'bridge-migrate[dashboard]'`)
so the core stays importable without them; they are imported inside `create_app`.
"""

from __future__ import annotations

import json
import os


def create_app(state_path: str):
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles

    state_path = os.path.abspath(state_path)
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

    app = FastAPI(title="Bridge", docs_url=None, redoc_url=None)

    @app.get("/api/state")
    def api_state():
        if not os.path.exists(state_path):
            return JSONResponse({"status": "NO_RUN"})
        with open(state_path, "r", encoding="utf-8") as fh:
            return JSONResponse(json.load(fh))

    # Mounted last so the /api route above takes precedence. html=True serves
    # index.html at "/".
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app
