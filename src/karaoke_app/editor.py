import json
import logging
import mimetypes
import socket
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

from karaoke_app.ass import generate_ass
from karaoke_app.job_document import load_job_document, resolve_job_asset
from karaoke_app.lyrics_file import load_lyrics_file, lyrics_to_transcript
from karaoke_app.style import StyleConfig

LOGGER = logging.getLogger(__name__)

CURATED_FONTS = [
    "Montserrat",
    "Poppins",
    "Roboto",
    "Bebas Neue",
    "Oswald",
    "Open Sans",
    "Lato",
    "Inter",
    "Playfair Display",
    "DejaVu Sans",
    "Arial",
    "Impact",
    "Trebuchet MS",
]


class KaraokeEditorHandler(SimpleHTTPRequestHandler):
    """Zero-dependency HTTP handler for the local karaoke style editor."""

    job_dir: Path
    document: dict[str, Any]
    transcript: dict[str, Any]

    def log_message(self, format_str: str, *args: Any) -> None:
        # Suppress routine request logs for a clean terminal output
        LOGGER.debug(format_str, *args)

    def do_GET(self) -> None:
        url = urllib.parse.urlparse(self.path)
        path = url.path.rstrip("/")

        if path in {"", "/index.html"}:
            self._serve_index()
        elif path == "/api/state":
            self._serve_api_state()
        elif path.startswith("/media/"):
            self._serve_media_asset(path.removeprefix("/media/"))
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Resource not found")

    def do_POST(self) -> None:
        url = urllib.parse.urlparse(self.path)
        path = url.path.rstrip("/")

        if path == "/api/save":
            self._handle_api_save()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def _serve_index(self) -> None:
        content = HTML_PAGE.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _serve_api_state(self) -> None:
        # Reload document from disk to ensure fresh state
        try:
            self.document = load_job_document(self.job_dir)
        except Exception as error:
            LOGGER.warning("Could not reload job.json: %s", error)

        state = {
            "title": self.document.get("title", ""),
            "job": self.document,
            "transcript": self.transcript,
            "available_fonts": CURATED_FONTS,
        }
        content = json.dumps(state, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _serve_media_asset(self, raw_path: str) -> None:
        decoded = urllib.parse.unquote(raw_path)
        try:
            asset_path = resolve_job_asset(self.job_dir, decoded, "asset")
        except (ValueError, FileNotFoundError):
            self.send_error(HTTPStatus.NOT_FOUND, "Asset not found or access denied")
            return

        mime_type, _ = mimetypes.guess_type(asset_path.name)
        if not mime_type:
            mime_type = "application/octet-stream"

        file_size = asset_path.stat().st_size
        range_header = self.headers.get("Range")

        if range_header and range_header.startswith("bytes="):
            try:
                byte_range = range_header.removeprefix("bytes=").split("-")
                start = int(byte_range[0]) if byte_range[0] else 0
                end = int(byte_range[1]) if byte_range[1] else file_size - 1
                start = max(0, min(start, file_size - 1))
                end = max(start, min(end, file_size - 1))
                length = end - start + 1

                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Type", mime_type)
                self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()

                with asset_path.open("rb") as f:
                    f.seek(start)
                    self.wfile.write(f.read(length))
                return
            except Exception:
                pass

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        with asset_path.open("rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)

    def _handle_api_save(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing payload")
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            style_data = payload.get("style", {})
            bg_data = payload.get("background", {})

            # Update in-memory document
            height = self.document["video"].get("height", 1080)
            style_config = StyleConfig.from_dict(style_data, height=height)
            self.document["style"] = style_config.to_dict()

            if "overlay_opacity" in bg_data:
                self.document["background"]["overlay_opacity"] = max(0.0, min(1.0, float(bg_data["overlay_opacity"])))
            if "color" in bg_data and bg_data["color"]:
                self.document["background"]["color"] = bg_data["color"]

            # Save job.json
            job_path = self.job_dir / "job.json"
            job_path.write_text(json.dumps(self.document, ensure_ascii=False, indent=2), encoding="utf-8")

            # Regenerate .ass files in job directory
            modes = ("karaoke", "lyrics")
            for mode in modes:
                ass_content = generate_ass(
                    self.transcript,
                    self.document["video"],
                    style=style_config,
                    scroll_long_lines=mode == "karaoke",
                )
                (self.job_dir / f"{mode}.ass").write_text(ass_content, encoding="utf-8")

            response_data = {"status": "ok", "message": "Estilos guardados y subtítulos .ass actualizados"}
            content = json.dumps(response_data).encode("utf-8")

            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as error:
            LOGGER.exception("Save failed")
            err_msg = json.dumps({"status": "error", "error": str(error)}).encode("utf-8")
            self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(err_msg)))
            self.end_headers()
            self.wfile.write(err_msg)


def find_free_port(preferred: int = 8765) -> int:
    """Find a free TCP port starting from preferred."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def run_editor_server(job_dir: Path, port: int = 8765, open_browser: bool = True) -> None:
    """Start the ultra-lightweight style editor server and open the browser."""
    root = job_dir.expanduser().resolve()
    document = load_job_document(root)
    lyrics_path = resolve_job_asset(root, document["media"]["lyrics"], "lyrics")
    lyrics = load_lyrics_file(lyrics_path, require_words=True)
    transcript = lyrics_to_transcript(lyrics)

    port = find_free_port(port)

    class CustomHandler(KaraokeEditorHandler):
        pass

    CustomHandler.job_dir = root
    CustomHandler.document = document
    CustomHandler.transcript = transcript

    server = HTTPServer(("127.0.0.1", port), CustomHandler)
    url = f"http://localhost:{port}/"

    print("\n=======================================================")
    print(" 🎨 Karaoke Style Editor en vivo")
    print(f" 📂 Job: {root.name}")
    print(f" 🌐 URL: {url}")
    print(" Presiona Ctrl+C para detener el editor.")
    print("=======================================================\n")

    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor del editor detenido.")
    finally:
        server.server_close()


HTML_PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Karaoke Style Studio</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link id="dynamic-font-link" rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700&family=Poppins:wght@400;700&family=Roboto:wght@400;700&family=Bebas+Neue&family=Oswald:wght@400;700&family=Open+Sans:wght@400;700&family=Lato:wght@400;700&family=Inter:wght@400;700&family=Playfair+Display:wght@400;700&display=swap">
  <style>
    :root {
      --bg-dark: #0f141c;
      --bg-panel: #18202c;
      --bg-input: #232d3d;
      --border: #2c384a;
      --accent: #00d7ff;
      --accent-hover: #00b8db;
      --text: #e2e8f0;
      --text-muted: #94a3b8;
      --success: #10b981;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg-dark);
      color: var(--text);
      display: flex;
      height: 100vh;
      overflow: hidden;
    }
    /* Layout */
    .main-area {
      flex: 1;
      display: flex;
      flex-direction: column;
      height: 100vh;
      padding: 16px;
      gap: 12px;
    }
    .top-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 4px 8px;
    }
    .track-title {
      font-size: 1.15rem;
      font-weight: 700;
      color: #fff;
    }
    .header-actions {
      display: flex;
      gap: 10px;
    }
    .viewport {
      flex: 1;
      background: #000;
      border-radius: 8px;
      border: 1px solid var(--border);
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    canvas {
      max-width: 100%;
      max-height: 100%;
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
      background: #0b1020;
    }
    .transport-bar {
      background: var(--bg-panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .scrubber-row {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .timeline {
      flex: 1;
      accent-color: var(--accent);
      cursor: pointer;
      height: 6px;
    }
    .time-label {
      font-family: monospace;
      font-size: 0.85rem;
      color: var(--text-muted);
      min-width: 90px;
      text-align: right;
    }
    .controls-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .play-controls {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    button.btn-icon {
      background: var(--bg-input);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 14px;
      border-radius: 6px;
      font-size: 0.9rem;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s;
    }
    button.btn-icon:hover {
      background: var(--border);
      border-color: var(--accent);
    }
    button.btn-primary {
      background: var(--accent);
      color: #0b1020;
      font-weight: 700;
      border: none;
      padding: 8px 18px;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.15s;
    }
    button.btn-primary:hover {
      background: var(--accent-hover);
    }
    /* Sidebar */
    .sidebar {
      width: 380px;
      background: var(--bg-panel);
      border-left: 1px solid var(--border);
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow-y: auto;
    }
    .sidebar-header {
      padding: 16px;
      border-bottom: 1px solid var(--border);
      font-weight: 700;
      font-size: 1.1rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .sidebar-content {
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }
    .control-group {
      display: flex;
      flex-direction: column;
      gap: 8px;
      background: var(--bg-dark);
      padding: 12px;
      border-radius: 8px;
      border: 1px solid var(--border);
    }
    .group-title {
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--accent);
      font-weight: 700;
      margin-bottom: 2px;
    }
    .form-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 0.85rem;
    }
    .form-row label {
      color: var(--text-muted);
    }
    select, input[type="text"], input[type="number"] {
      background: var(--bg-input);
      border: 1px solid var(--border);
      color: #fff;
      padding: 5px 8px;
      border-radius: 4px;
      font-size: 0.85rem;
      outline: none;
    }
    select:focus, input:focus {
      border-color: var(--accent);
    }
    .color-input-wrap {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    input[type="color"] {
      -webkit-appearance: none;
      border: 1px solid var(--border);
      border-radius: 4px;
      width: 32px;
      height: 26px;
      cursor: pointer;
      background: none;
      padding: 0;
    }
    input[type="color"]::-webkit-color-swatch-wrapper { padding: 0; }
    input[type="color"]::-webkit-color-swatch { border: none; border-radius: 3px; }
    .color-hex {
      font-family: monospace;
      width: 76px;
      text-align: center;
    }
    .range-wrap {
      display: flex;
      align-items: center;
      gap: 8px;
      flex: 1;
      justify-content: flex-end;
    }
    .range-wrap input[type="range"] {
      width: 130px;
      accent-color: var(--accent);
      cursor: pointer;
    }
    .val-badge {
      font-family: monospace;
      font-size: 0.8rem;
      min-width: 36px;
      text-align: right;
      color: var(--text-muted);
    }
    .checkbox-wrap {
      display: flex;
      gap: 14px;
    }
    .checkbox-item {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.85rem;
      cursor: pointer;
    }
    .toast {
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%);
      background: var(--success);
      color: #0b1020;
      font-weight: 700;
      padding: 10px 20px;
      border-radius: 6px;
      box-shadow: 0 4px 12px rgba(0,0,0,0.4);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.25s ease;
      z-index: 1000;
    }
    .toast.show {
      opacity: 1;
    }
  </style>
</head>
<body>

  <div class="main-area">
    <div class="top-bar">
      <div class="track-title" id="track-title">Cargando proyecto...</div>
      <div class="header-actions">
        <button class="btn-icon" id="btn-snapshot" title="Descargar fotograma actual">📷 Snapshot PNG</button>
        <button class="btn-primary" id="btn-save">💾 Guardar Estilos</button>
      </div>
    </div>

    <div class="viewport">
      <canvas id="preview-canvas" width="1920" height="1080"></canvas>
    </div>

    <div class="transport-bar">
      <div class="scrubber-row">
        <input type="range" class="timeline" id="timeline" min="0" max="100" step="0.01" value="0">
        <div class="time-label" id="time-display">00:00 / 00:00</div>
      </div>
      <div class="controls-row">
        <div class="play-controls">
          <button class="btn-icon" id="btn-play">▶ Play</button>
          <button class="btn-icon" id="btn-back5">-5s</button>
          <button class="btn-icon" id="btn-fwd5">+5s</button>
          <select id="audio-source-select" title="Pista de audio">
            <option value="instrumental">Audio Instrumental</option>
            <option value="vocals">Pista de Voz</option>
            <option value="original">Audio Original</option>
          </select>
        </div>
        <div style="font-size: 0.8rem; color: var(--text-muted);">
          Resolución: <span id="res-badge">1920x1080</span>
        </div>
      </div>
    </div>
  </div>

  <div class="sidebar">
    <div class="sidebar-header">
      <span>🎨 Inspector de Estilos</span>
    </div>
    <div class="sidebar-content">

      <!-- Tipografía -->
      <div class="control-group">
        <div class="group-title">Tipografía</div>
        <div class="form-row">
          <label for="font-family">Fuente</label>
          <select id="font-family" style="width: 190px;"></select>
        </div>
        <div class="form-row">
          <label for="font-size">Tamaño</label>
          <div class="range-wrap">
            <input type="range" id="font-size" min="24" max="120" value="64">
            <span class="val-badge" id="val-font-size">64px</span>
          </div>
        </div>
        <div class="form-row">
          <label>Estilo</label>
          <div class="checkbox-wrap">
            <label class="checkbox-item"><input type="checkbox" id="font-bold" checked> Negrita</label>
            <label class="checkbox-item"><input type="checkbox" id="font-italic"> Cursiva</label>
          </div>
        </div>
        <div class="form-row">
          <label for="line-gap">Interlineado</label>
          <div class="range-wrap">
            <input type="range" id="line-gap" min="1.0" max="2.2" step="0.05" value="1.35">
            <span class="val-badge" id="val-line-gap">1.35x</span>
          </div>
        </div>
      </div>

      <!-- Paleta de Colores -->
      <div class="control-group">
        <div class="group-title">Colores de Letra</div>
        <div class="form-row">
          <label>Texto Normal</label>
          <div class="color-input-wrap">
            <input type="color" id="col-primary" value="#FFD700">
            <input type="text" class="color-hex" id="hex-primary" value="#FFD700" maxlength="7">
          </div>
        </div>
        <div class="form-row">
          <label>Resalte Karaoke</label>
          <div class="color-input-wrap">
            <input type="color" id="col-highlight" value="#FFFFFF">
            <input type="text" class="color-hex" id="hex-highlight" value="#FFFFFF" maxlength="7">
          </div>
        </div>
      </div>

      <!-- Contorno y Sombra -->
      <div class="control-group">
        <div class="group-title">Borde y Sombra</div>
        <div class="form-row">
          <label>Color Borde</label>
          <div class="color-input-wrap">
            <input type="color" id="col-outline" value="#000000">
            <input type="text" class="color-hex" id="hex-outline" value="#000000" maxlength="7">
          </div>
        </div>
        <div class="form-row">
          <label for="outline-width">Grosor Borde</label>
          <div class="range-wrap">
            <input type="range" id="outline-width" min="0" max="15" value="4">
            <span class="val-badge" id="val-outline-width">4px</span>
          </div>
        </div>
        <div class="form-row">
          <label>Color Sombra</label>
          <div class="color-input-wrap">
            <input type="color" id="col-shadow" value="#000000">
            <input type="text" class="color-hex" id="hex-shadow" value="#000000" maxlength="7">
          </div>
        </div>
        <div class="form-row">
          <label for="shadow-depth">Distancia Sombra</label>
          <div class="range-wrap">
            <input type="range" id="shadow-depth" min="0" max="10" value="1">
            <span class="val-badge" id="val-shadow-depth">1px</span>
          </div>
        </div>
        <div class="form-row">
          <label for="shadow-opacity">Opacidad Sombra</label>
          <div class="range-wrap">
            <input type="range" id="shadow-opacity" min="0" max="1" step="0.05" value="0.44">
            <span class="val-badge" id="val-shadow-opacity">44%</span>
          </div>
        </div>
      </div>

      <!-- Márgenes y Fondo -->
      <div class="control-group">
        <div class="group-title">Fondo y Márgenes</div>
        <div class="form-row">
          <label for="margin-h">Margen Lateral</label>
          <div class="range-wrap">
            <input type="range" id="margin-h" min="20" max="250" value="70">
            <span class="val-badge" id="val-margin-h">70px</span>
          </div>
        </div>
        <div class="form-row">
          <label for="margin-v">Margen Vertical</label>
          <div class="range-wrap">
            <input type="range" id="margin-v" min="20" max="250" value="70">
            <span class="val-badge" id="val-margin-v">70px</span>
          </div>
        </div>
        <div class="form-row">
          <label for="overlay-opacity">Oscurecer Fondo</label>
          <div class="range-wrap">
            <input type="range" id="overlay-opacity" min="0" max="1" step="0.02" value="0.38">
            <span class="val-badge" id="val-overlay-opacity">38%</span>
          </div>
        </div>
        <div class="form-row" id="bg-color-row">
          <label>Color Fondo Sólido</label>
          <div class="color-input-wrap">
            <input type="color" id="col-bg" value="#0B1020">
            <input type="text" class="color-hex" id="hex-bg" value="#0B1020" maxlength="7">
          </div>
        </div>
      </div>

    </div>
  </div>

  <audio id="audio-player" preload="auto"></audio>
  <div class="toast" id="toast">Cambios guardados</div>

  <script>
    let state = null;
    let bgImage = null;
    let bgLoaded = false;
    const canvas = document.getElementById('preview-canvas');
    const ctx = canvas.getContext('2d');
    const audio = document.getElementById('audio-player');
    const timeline = document.getElementById('timeline');
    const timeDisplay = document.getElementById('time-display');
    const btnPlay = document.getElementById('btn-play');
    const toast = document.getElementById('toast');

    // Load initial state from server
    async function init() {
      const res = await fetch('/api/state');
      state = await res.json();
      
      document.getElementById('track-title').textContent = state.title || 'Karaoke Studio';
      const width = state.job.video?.width || 1920;
      const height = state.job.video?.height || 1080;
      canvas.width = width;
      canvas.height = height;
      document.getElementById('res-badge').textContent = `${width}x${height}`;

      // Populate fonts
      const fontSelect = document.getElementById('font-family');
      state.available_fonts.forEach(font => {
        const opt = document.createElement('option');
        opt.value = font;
        opt.textContent = font;
        fontSelect.appendChild(opt);
      });

      // Populate inputs with current style
      const style = state.job.style || {};
      if (style.font_family) fontSelect.value = style.font_family;
      if (style.font_size) setInputVal('font-size', style.font_size, 'px');
      document.getElementById('font-bold').checked = style.bold !== undefined ? style.bold : true;
      document.getElementById('font-italic').checked = !!style.italic;
      if (style.line_gap_factor) setInputVal('line-gap', style.line_gap_factor, 'x');
      
      syncColor('primary', style.primary_color || '#FFD700');
      syncColor('highlight', style.highlight_color || '#FFFFFF');
      syncColor('outline', style.outline_color || '#000000');
      if (style.outline_width !== undefined) setInputVal('outline-width', style.outline_width, 'px');
      syncColor('shadow', style.shadow_color || '#000000');
      if (style.shadow_depth !== undefined) setInputVal('shadow-depth', style.shadow_depth, 'px');
      if (style.shadow_opacity !== undefined) setInputVal('shadow-opacity', style.shadow_opacity, '%', true);
      if (style.margin_h !== undefined) setInputVal('margin-h', style.margin_h, 'px');
      if (style.margin_v !== undefined) setInputVal('margin-v', style.margin_v, 'px');

      const bg = state.job.background || {};
      const overlayVal = bg.overlay_opacity !== undefined ? bg.overlay_opacity : (style.overlay_opacity || 0.38);
      setInputVal('overlay-opacity', overlayVal, '%', true);
      syncColor('bg', bg.color || '#0B1020');

      // Load background image if available
      if (bg.kind === 'image' && bg.path) {
        bgImage = new Image();
        bgImage.crossOrigin = 'anonymous';
        bgImage.src = `/media/${encodeURIComponent(bg.path)}`;
        bgImage.onload = () => { bgLoaded = true; renderFrame(); };
      }

      // Audio setup
      updateAudioSource();
      setupEventListeners();
      renderFrame();
    }

    function setInputVal(id, val, unit = '', isPercent = false) {
      const el = document.getElementById(id);
      if (el) el.value = val;
      const badge = document.getElementById(`val-${id}`);
      if (badge) badge.textContent = isPercent ? `${Math.round(val * 100)}%` : `${val}${unit}`;
    }

    function syncColor(id, hex) {
      const col = document.getElementById(`col-${id}`);
      const txt = document.getElementById(`hex-${id}`);
      if (col && txt) {
        col.value = hex;
        txt.value = hex.toUpperCase();
      }
    }

    function updateAudioSource() {
      const type = document.getElementById('audio-source-select').value;
      const media = state.job.media || {};
      let filename = media.instrumental_audio;
      if (type === 'vocals') filename = media.vocals_audio;
      if (type === 'original') filename = media.original_audio;
      if (filename) {
        audio.src = `/media/${encodeURIComponent(filename)}`;
      }
    }

    function setupEventListeners() {
      // Audio transport
      btnPlay.addEventListener('click', () => {
        if (audio.paused) { audio.play(); btnPlay.textContent = '⏸ Pause'; }
        else { audio.pause(); btnPlay.textContent = '▶ Play'; }
      });
      document.getElementById('btn-back5').addEventListener('click', () => {
        audio.currentTime = Math.max(0, audio.currentTime - 5);
      });
      document.getElementById('btn-fwd5').addEventListener('click', () => {
        audio.currentTime = Math.min(audio.duration || 100, audio.currentTime + 5);
      });
      document.getElementById('audio-source-select').addEventListener('change', updateAudioSource);

      audio.addEventListener('timeupdate', () => {
        if (!audio.duration) return;
        timeline.value = (audio.currentTime / audio.duration) * 100;
        timeDisplay.textContent = `${fmtTime(audio.currentTime)} / ${fmtTime(audio.duration)}`;
        renderFrame();
      });

      timeline.addEventListener('input', () => {
        if (!audio.duration) return;
        audio.currentTime = (timeline.value / 100) * audio.duration;
        renderFrame();
      });

      // Controls change listeners
      const inputs = [
        'font-size', 'line-gap', 'outline-width', 'shadow-depth',
        'shadow-opacity', 'margin-h', 'margin-v', 'overlay-opacity'
      ];
      inputs.forEach(id => {
        const el = document.getElementById(id);
        el.addEventListener('input', () => {
          const isPercent = id.includes('opacity');
          const unit = id.includes('gap') ? 'x' : 'px';
          setInputVal(id, el.value, unit, isPercent);
          renderFrame();
        });
      });

      ['font-family', 'font-bold', 'font-italic'].forEach(id => {
        document.getElementById(id).addEventListener('change', renderFrame);
      });

      ['primary', 'highlight', 'outline', 'shadow', 'bg'].forEach(id => {
        const col = document.getElementById(`col-${id}`);
        const txt = document.getElementById(`hex-${id}`);
        col.addEventListener('input', () => { txt.value = col.value.toUpperCase(); renderFrame(); });
        txt.addEventListener('input', () => {
          if (/^#[0-9A-Fa-f]{6}$/.test(txt.value)) { col.value = txt.value; renderFrame(); }
        });
      });

      // Actions
      document.getElementById('btn-save').addEventListener('click', saveStyles);
      document.getElementById('btn-snapshot').addEventListener('click', exportSnapshot);
    }

    function fmtTime(sec) {
      const m = Math.floor(sec / 60);
      const s = Math.floor(sec % 60);
      return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }

    function getActiveStyle() {
      return {
        font_family: document.getElementById('font-family').value,
        font_size: parseInt(document.getElementById('font-size').value, 10),
        bold: document.getElementById('font-bold').checked,
        italic: document.getElementById('font-italic').checked,
        line_gap_factor: parseFloat(document.getElementById('line-gap').value),
        primary_color: document.getElementById('col-primary').value,
        highlight_color: document.getElementById('col-highlight').value,
        outline_color: document.getElementById('col-outline').value,
        outline_width: parseInt(document.getElementById('outline-width').value, 10),
        shadow_color: document.getElementById('col-shadow').value,
        shadow_depth: parseInt(document.getElementById('shadow-depth').value, 10),
        shadow_opacity: parseFloat(document.getElementById('shadow-opacity').value),
        margin_h: parseInt(document.getElementById('margin-h').value, 10),
        margin_v: parseInt(document.getElementById('margin-v').value, 10),
      };
    }

    function renderFrame() {
      const W = canvas.width;
      const H = canvas.height;
      const style = getActiveStyle();
      const overlayOpacity = parseFloat(document.getElementById('overlay-opacity').value);
      const bgColor = document.getElementById('col-bg').value;

      // 1. Draw Background
      ctx.clearRect(0, 0, W, H);
      if (bgLoaded && bgImage) {
        const imgRatio = bgImage.width / bgImage.height;
        const canvasRatio = W / H;
        let dw, dh, dx, dy;
        if (imgRatio > canvasRatio) {
          dh = H; dw = H * imgRatio;
          dx = (W - dw) / 2; dy = 0;
        } else {
          dw = W; dh = W / imgRatio;
          dx = 0; dy = (H - dh) / 2;
        }
        ctx.drawImage(bgImage, dx, dy, dw, dh);
      } else {
        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, W, H);
      }

      // Dark overlay
      if (overlayOpacity > 0) {
        ctx.fillStyle = `rgba(0, 0, 0, ${overlayOpacity})`;
        ctx.fillRect(0, 0, W, H);
      }

      // 2. Find active page / lyric lines for currentTime
      const currentTime = audio.currentTime || 0;
      const segments = state?.transcript?.segments || [];
      const activeSeg = segments.find(
        s => currentTime >= s.start - 0.35 && currentTime <= s.end + 0.35
      ) || segments[0];

      if (!activeSeg) return;

      // Split lines if long or multiple
      const lines = [activeSeg];
      const fontPrefix = `${style.italic ? 'italic ' : ''}${style.bold ? 'bold ' : ''}`;
      const fontStr = `${fontPrefix}${style.font_size}px "${style.font_family}", sans-serif`;
      ctx.font = fontStr;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      const lineGap = Math.round(style.font_size * style.line_gap_factor);
      const startY = Math.round(H / 2);

      lines.forEach((seg, idx) => {
        const y = startY + (idx - (lines.length - 1) / 2) * lineGap;
        const fullText = seg.text || '';
        const words = seg.words || [{ start: seg.start, end: seg.end, text: fullText }];
        
        // Measure word widths to compute exact karaoke progress
        let totalLineWidth = ctx.measureText(fullText).width;
        let currentX = (W / 2) - (totalLineWidth / 2);

        // Draw shadow
        if (style.shadow_depth > 0) {
          ctx.save();
          ctx.shadowColor = `rgba(0, 0, 0, ${style.shadow_opacity})`;
          ctx.shadowOffsetX = style.shadow_depth * 2;
          ctx.shadowOffsetY = style.shadow_depth * 2;
          ctx.shadowBlur = 4;
        }

        // Render each word
        words.forEach(word => {
          const wordText = word.text + ' ';
          const wordWidth = ctx.measureText(wordText).width;
          const wordCenterX = currentX + (wordWidth / 2);

          // Base outline
          if (style.outline_width > 0) {
            ctx.strokeStyle = style.outline_color;
            ctx.lineWidth = style.outline_width * 2;
            ctx.lineJoin = 'round';
            ctx.strokeText(wordText, wordCenterX, y);
          }

          // Inactive base color
          ctx.fillStyle = style.primary_color;
          ctx.fillText(wordText, wordCenterX, y);

          // Active karaoke highlight wipe
          if (currentTime >= word.start) {
            ctx.save();
            let progress = 1.0;
            if (currentTime < word.end && word.end > word.start) {
              progress = (currentTime - word.start) / (word.end - word.start);
            }
            // Clip region for sung portion
            const clipWidth = wordWidth * progress;
            ctx.beginPath();
            ctx.rect(currentX, y - (style.font_size), clipWidth, style.font_size * 2);
            ctx.clip();

            // Re-draw with highlight color inside clip
            if (style.outline_width > 0) {
              ctx.strokeStyle = style.outline_color;
              ctx.lineWidth = style.outline_width * 2;
              ctx.lineJoin = 'round';
              ctx.strokeText(wordText, wordCenterX, y);
            }
            ctx.fillStyle = style.highlight_color;
            ctx.fillText(wordText, wordCenterX, y);
            ctx.restore();
          }

          currentX += wordWidth;
        });

        if (style.shadow_depth > 0) {
          ctx.restore();
        }
      });
    }

    async function saveStyles() {
      const style = getActiveStyle();
      const overlay_opacity = parseFloat(document.getElementById('overlay-opacity').value);
      const color = document.getElementById('col-bg').value;

      try {
        const res = await fetch('/api/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ style, background: { overlay_opacity, color } })
        });
        const data = await res.json();
        showToast(data.message || 'Estilos guardados');
      } catch (err) {
        showToast('Error al guardar estilos');
      }
    }

    function exportSnapshot() {
      const link = document.createElement('a');
      link.download = `snapshot_${fmtTime(audio.currentTime || 0).replace(':', '-')}.png`;
      link.href = canvas.toDataURL('image/png');
      link.click();
      showToast('Fotograma descargado');
    }

    function showToast(msg) {
      toast.textContent = msg;
      toast.classList.add('show');
      setTimeout(() => toast.classList.remove('show'), 2500);
    }

    window.addEventListener('DOMContentLoaded', init);
  </script>
</body>
</html>
"""
