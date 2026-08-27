import logging
import secrets
import socket
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import quote

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from karaoke_app.edit_document import (
    RevisionConflictError,
    load_edit_document,
    resolve_original_audio,
    save_edit_document_revision,
)

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EDITOR_ROOT = PROJECT_ROOT / "editor"


def create_app(job_dir: Path, token: str, api_origin: str, editor_origin: str, build_dir: Path) -> FastAPI:
    """Create the loopback API for one prepared job."""
    app = FastAPI(title="Karaoke editor API", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[api_origin, editor_origin],
        allow_methods=["GET", "PUT"],
        allow_headers=["Content-Type", "X-Karaoke-Token"],
    )

    def authorize(
        header_token: str | None = Header(default=None, alias="X-Karaoke-Token"),
        query_token: str | None = Query(default=None, alias="token"),
    ) -> None:
        supplied = header_token or query_token or ""
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(status_code=403, detail="Invalid editor token")

    @app.get("/api/job", dependencies=[Depends(authorize)])
    def get_job() -> dict[str, object]:
        try:
            document = load_edit_document(job_dir)
            audio, _ = resolve_original_audio(job_dir)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        asset_url = f"{api_origin}/api/audio?token={quote(token, safe='')}"
        return {
            "edit": document,
            "media": {"url": asset_url, "name": Path(audio).name, "type": "audio"},
        }

    @app.put("/api/job", dependencies=[Depends(authorize)])
    def put_job(document: dict[str, object]) -> dict[str, object]:
        try:
            return {"edit": save_edit_document_revision(job_dir, document)}
        except RevisionConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/audio", dependencies=[Depends(authorize)])
    def get_audio() -> FileResponse:
        try:
            _, asset = resolve_original_audio(job_dir)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(asset)

    if (build_dir / "index.html").is_file():
        app.mount("/", StaticFiles(directory=build_dir, html=True), name="editor")
    return app


def serve_editor(job_dir: Path, port: int = 0, editor_port: int = 5173) -> None:
    """Start the local API and open the React editor."""
    root = job_dir.expanduser().resolve()
    load_edit_document(root)
    api_port = port or _available_port()
    api_origin = f"http://127.0.0.1:{api_port}"
    token = secrets.token_urlsafe(32)
    build_dir = EDITOR_ROOT / "dist"
    vite_process: subprocess.Popen[bytes] | None = None
    vite = EDITOR_ROOT / "node_modules" / ".bin" / "vite"
    if vite.is_file():
        editor_origin = f"http://127.0.0.1:{editor_port}"
        vite_process = subprocess.Popen(
            [str(vite), "--host", "127.0.0.1", "--port", str(editor_port), "--strictPort"],
            cwd=EDITOR_ROOT,
        )
    elif (build_dir / "index.html").is_file():
        editor_origin = api_origin
    else:
        raise RuntimeError("The editor requires installed Vite dependencies or an existing editor/dist build.")

    app = create_app(root, token, api_origin, editor_origin, build_dir)
    editor_url = f"{editor_origin}/?api={quote(api_origin, safe='')}&token={quote(token, safe='')}"
    LOGGER.info("Editor ready at %s", editor_url)
    webbrowser.open(editor_url)
    try:
        uvicorn.run(app, host="127.0.0.1", port=api_port, log_level="info")
    finally:
        if vite_process is not None and vite_process.poll() is None:
            vite_process.terminate()
            try:
                vite_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                vite_process.kill()


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])
