import logging
import shutil
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse

from freemocap.system.paths_and_filenames.file_and_folder_names import SYNCHRONIZED_VIDEOS_FOLDER_NAME
from freemocap.system.paths_and_filenames.path_getters import (
    get_recording_session_folder_path,
    create_new_default_recording_name,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/recordings", tags=["recordings"])

_ALLOWED_VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv"}


def _sessions_root() -> Path:
    return Path(get_recording_session_folder_path(create_folder=True))


def _safe_recording_path(recording_id: str) -> Path:
    """
    Resolve the recording folder path and verify it stays within the sessions
    root to prevent path-traversal attacks.

    Raises ``HTTPException(400)`` if the resolved path escapes the root.
    """
    root = _sessions_root().resolve()
    candidate = (root / recording_id).resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(status_code=400, detail="Invalid recording ID")
    return candidate


def _list_recording_folders() -> List[Path]:
    sessions_root = _sessions_root()
    folders = []
    for session_dir in sorted(sessions_root.iterdir()):
        if session_dir.is_dir():
            for rec_dir in sorted(session_dir.iterdir()):
                if rec_dir.is_dir():
                    folders.append(rec_dir)
    return folders


@router.get("", summary="List all recordings")
def list_recordings():
    """Return a list of recording IDs (folder names) found on the server."""
    root = _sessions_root()
    folders = _list_recording_folders()
    return [
        {
            "id": str(folder.relative_to(root)),
            "name": folder.name,
            "path": str(folder),
        }
        for folder in folders
    ]


@router.post("/upload", summary="Upload one or more video files to create a new recording")
async def upload_videos(files: List[UploadFile] = File(...)):
    """
    Accept one or more video files (.mp4 / .avi / .mov / .mkv) and store them
    in a new recording folder's ``synchronized_videos/`` sub-directory.

    Returns the recording ``id`` that can be passed to the ``/process`` endpoint.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    recording_name = create_new_default_recording_name()
    videos_folder = _sessions_root() / recording_name / SYNCHRONIZED_VIDEOS_FOLDER_NAME
    videos_folder.mkdir(parents=True, exist_ok=True)

    saved = []
    for upload in files:
        # Derive a safe filename; fall back to a random UUID if none provided
        original_name = upload.filename or ""
        suffix = Path(original_name).suffix.lower() if original_name else ""
        if suffix not in _ALLOWED_VIDEO_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{suffix or '(none)'}'. "
                       f"Accepted: {', '.join(sorted(_ALLOWED_VIDEO_SUFFIXES))}",
            )
        # Use only the basename to avoid any directory components in the filename
        safe_stem = Path(original_name).stem if original_name else str(uuid.uuid4())
        dest = videos_folder / f"{safe_stem}{suffix}"
        try:
            with dest.open("wb") as fh:
                shutil.copyfileobj(upload.file, fh)
        finally:
            await upload.close()
        saved.append(dest.name)

    recording_id = recording_name
    logger.info(f"Uploaded {len(saved)} file(s) to recording '{recording_id}'")
    return JSONResponse(
        status_code=201,
        content={
            "recording_id": recording_id,
            "recording_path": str(videos_folder.parent),
            "uploaded_files": saved,
        },
    )


@router.get("/{recording_id}", summary="Get the status of a recording folder")
def recording_status(recording_id: str):
    """
    Return the ``RecordingInfoModel`` status check dict for the given recording.
    """
    recording_path = _safe_recording_path(recording_id)
    if not recording_path.exists():
        raise HTTPException(status_code=404, detail=f"Recording '{recording_id}' not found")

    try:
        from freemocap.data_layer.recording_models.recording_info_model import RecordingInfoModel

        info = RecordingInfoModel(recording_folder_path=recording_path)
        return info.status_check
    except Exception as exc:
        logger.exception(exc)
        raise HTTPException(status_code=500, detail=str(exc))
