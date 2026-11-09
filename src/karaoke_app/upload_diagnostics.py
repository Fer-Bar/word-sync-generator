"""Size estimates and actionable diagnostics for Colab uploads."""

import logging
import re
from pathlib import Path

LOGGER = logging.getLogger(__name__)
LARGE_UPLOAD_BYTES = 64 * 1024 * 1024


def upload_size(path: Path) -> str:
    """Describe the file and estimated base64 payload, excluding JSON overhead."""
    size = path.stat().st_size
    encoded = 4 * ((size + 2) // 3)
    return f"{path.name}: {size / 1024**2:.1f} MiB; estimated base64 payload {encoded / 1024**2:.1f} MiB"


def warn_large_upload(path: Path) -> None:
    """Warn before allocating Colab; the threshold is advisory, not a server limit."""
    if path.stat().st_size >= LARGE_UPLOAD_BYTES:
        LOGGER.warning(
            "Large Colab upload (%s). The client sends the whole file in one request. "
            "64 MiB is an advisory threshold, not a confirmed Colab limit. "
            "If rejected, reduce the background bitrate or use lossless compressed audio instead of WAV.",
            upload_size(path),
        )


def upload_failure_message(path: Path, cause: str) -> str:
    """Explain an upload failure without inferring a size limit from HTTP 400."""
    if re.search(r"\b413\b|payload too large|request entity too large|content too large", cause, re.I):
        hint = (
            "Colab rejected the request as too large (HTTP 413 / payload too large). "
            "Reduce the background bitrate or use lossless compressed audio instead of WAV, then retry."
        )
    elif re.search(r"\b400\b", cause):
        hint = (
            "Colab rejected the upload (HTTP 400). File size is a possible cause, not confirmed by this status. "
            "For a large package, try reducing the background bitrate or replacing WAV with lossless compressed audio. "
            "If a smaller upload also fails, check the Colab session and client diagnostics."
        )
    else:
        hint = "The upload failed; there is no evidence here that file size caused it. Check the error below."
    return f"Upload failed ({upload_size(path)}). {hint}\nOriginal error: {cause}"
