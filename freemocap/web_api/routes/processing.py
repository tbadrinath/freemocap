import logging
import re
import threading
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException

from freemocap.system.paths_and_filenames.path_getters import get_recording_session_folder_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/process", tags=["processing"])

# In-memory job registry  {recording_id: {"status": str, "error": str|None}}
_jobs: Dict[str, dict] = {}
_jobs_lock = threading.Lock()

# Only allow word chars, hyphens, dots, and forward-slashes (session/recording hierarchy)
_SAFE_ID_RE = re.compile(r'^[\w][\w.\-]*(\/[\w][\w.\-]*)*$')


def _validate_recording_id(recording_id: str) -> None:
    """
    Reject recording IDs that contain path-traversal sequences or absolute paths.

    Raises ``HTTPException(400)`` for invalid IDs.
    """
    if not _SAFE_ID_RE.match(recording_id):
        raise HTTPException(status_code=400, detail="Invalid recording ID")
    # Belt-and-suspenders: reject any '..' component
    for part in recording_id.split('/'):
        if part in ('..', '.', ''):
            raise HTTPException(status_code=400, detail="Invalid recording ID")


def _safe_recording_path(recording_id: str) -> Path:
    """
    Validate ``recording_id`` then resolve its path within the sessions root.

    Raises ``HTTPException(400)`` if the path would escape the sessions root.
    """
    _validate_recording_id(recording_id)
    sessions_root = Path(get_recording_session_folder_path(create_folder=False)).resolve()
    # Safe to join: recording_id has already been validated to contain no '..'
    candidate = sessions_root / recording_id
    return candidate


def _run_processing(recording_id: str, recording_path: Path, calibration_toml: Optional[str]) -> None:
    """Background thread that runs process_recording_headless."""
    try:
        from freemocap.core_processes.process_motion_capture_videos.process_recording_headless import (
            process_recording_headless,
        )

        process_recording_headless(
            recording_path=recording_path,
            path_to_camera_calibration_toml=calibration_toml,
            run_blender=False,
            make_jupyter_notebook=False,
            use_tqdm=False,
        )
        with _jobs_lock:
            _jobs[recording_id]["status"] = "complete"
        logger.info(f"Processing complete for recording '{recording_id}'")
    except Exception as exc:
        logger.exception(exc)
        with _jobs_lock:
            _jobs[recording_id] = {"status": "failed", "error": str(exc)}


@router.post("/{recording_id}", summary="Start processing a recording")
def start_processing(recording_id: str, calibration_toml: Optional[str] = None):
    """
    Kick off the FreeMoCap processing pipeline for ``recording_id`` in a
    background thread.  Use ``GET /process/{recording_id}`` to poll status.

    - ``calibration_toml`` (optional query param): absolute server-side path to
      the camera calibration TOML file.  Required for multi-camera recordings.
    """
    recording_path = _safe_recording_path(recording_id)
    if not recording_path.exists():
        raise HTTPException(status_code=404, detail=f"Recording '{recording_id}' not found")

    with _jobs_lock:
        if recording_id in _jobs and _jobs[recording_id]["status"] == "running":
            raise HTTPException(status_code=409, detail="Processing already in progress for this recording")
        # Mark as running while still holding the lock to prevent TOCTOU race
        _jobs[recording_id] = {"status": "running", "error": None}

    thread = threading.Thread(
        target=_run_processing,
        args=(recording_id, recording_path, calibration_toml),
        daemon=True,
        name=f"freemocap-process-{recording_id}",
    )
    thread.start()

    return {"recording_id": recording_id, "status": "started"}


@router.get("/{recording_id}", summary="Poll processing status")
def get_processing_status(recording_id: str):
    """
    Return the current processing status for ``recording_id``.

    Possible values: ``"pending"`` | ``"running"`` | ``"complete"`` | ``"failed"``
    """
    with _jobs_lock:
        job = _jobs.get(recording_id)

    if job is None:
        return {"recording_id": recording_id, "status": "pending"}

    return {"recording_id": recording_id, **job}
