"""Locating and running external media tools.

FFmpeg is always started with an argument list, never through a shell, so no part of a
path or a model-generated value can be interpreted as a command.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class ToolNotFound(RuntimeError):
    pass


def find_tool(name: str) -> str:
    """Return the path of ffmpeg/ffprobe.

    CINEFLOW_<NAME> (e.g. CINEFLOW_FFPROBE) wins over PATH. The bundled copy planned for the
    installer (DECISIONS D-013) will be checked here too once it exists.
    """
    override = os.environ.get(f"CINEFLOW_{name.upper()}")
    if override:
        if not Path(override).is_file():
            raise ToolNotFound(f"CINEFLOW_{name.upper()} points to a missing file: {override}")
        return override
    found = shutil.which(name)
    if not found:
        raise ToolNotFound(f"{name} not found on PATH; set CINEFLOW_{name.upper()}")
    return found


def run(args: list[str], timeout: float = 120) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, capture_output=True, timeout=timeout, check=False)
