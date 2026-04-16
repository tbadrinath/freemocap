import logging
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


def _safe_recording_path(recording_id: str) -> Path:
    """
    Resolve the recording folder path and verify it stays within the sessions
    root to prevent path-traversal attacks.

    Raises ``HTTPException(400)`` if the resolved path escapes the root.
    """
    sessions_root = Path(get_recording_session_folder_path(create_folder=False)).resolve()
    candidate = (sessions_root / recording_id).resolve()
    if sessions_root not in candidate.parents and candidate != sessions_root:
        raise HTTPException(status_code=400, detail="Invalid recording ID")
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
