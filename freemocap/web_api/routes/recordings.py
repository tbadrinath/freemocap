import logging
import shutil
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


def _list_recording_folders() -> List[Path]:
    sessions_root = Path(get_recording_session_folder_path(create_folder=True))
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
    folders = _list_recording_folders()
    return [
        {
            "id": str(folder.relative_to(Path(get_recording_session_folder_path(create_folder=False)))),
            "name": folder.name,
            "path": str(folder),
        }
        for folder in folders
    ]


@router.post("/upload", summary="Upload one or more video files to create a new recording")
async def upload_videos(files: List[UploadFile] = File(...)):
    """
    Accept one or more video files (.mp4 / .avi / .mov) and store them in a new
    recording folder's ``synchronized_videos/`` sub-directory.

    Returns the recording ``id`` that can be passed to the ``/process`` endpoint.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    recording_name = create_new_default_recording_name()
    sessions_root = Path(get_recording_session_folder_path(create_folder=True))

    # Use a simple flat layout: <sessions_root>/<recording_name>/synchronized_videos/
    recording_folder = sessions_root / recording_name
    videos_folder = recording_folder / SYNCHRONIZED_VIDEOS_FOLDER_NAME
    videos_folder.mkdir(parents=True, exist_ok=True)

    saved = []
    for upload in files:
        suffix = Path(upload.filename).suffix.lower() if upload.filename else ".mp4"
        if suffix not in {".mp4", ".avi", ".mov", ".mkv"}:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{suffix}'. Accepted: .mp4, .avi, .mov, .mkv",
            )
        dest = videos_folder / upload.filename
        try:
            with dest.open("wb") as fh:
                shutil.copyfileobj(upload.file, fh)
        finally:
            await upload.close()
        saved.append(upload.filename)

    recording_id = recording_name
    logger.info(f"Uploaded {len(saved)} file(s) to recording '{recording_id}'")
    return JSONResponse(
        status_code=201,
        content={
            "recording_id": recording_id,
            "recording_path": str(recording_folder),
            "uploaded_files": saved,
        },
    )


@router.get("/{recording_id}/status", summary="Get the status of a recording folder")
def recording_status(recording_id: str):
    """
    Return the ``RecordingInfoModel`` status check dict for the given recording.
    """
    sessions_root = Path(get_recording_session_folder_path(create_folder=False))
    recording_path = sessions_root / recording_id
    if not recording_path.exists():
        raise HTTPException(status_code=404, detail=f"Recording '{recording_id}' not found")

    try:
        from freemocap.data_layer.recording_models.recording_info_model import RecordingInfoModel

        info = RecordingInfoModel(recording_folder_path=recording_path)
        return info.status_check
    except Exception as exc:
        logger.exception(exc)
        raise HTTPException(status_code=500, detail=str(exc))
