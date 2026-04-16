"""
FreeMoCap Web API Server
========================

Starts a FastAPI application that exposes the FreeMoCap processing pipeline
over HTTP and serves the companion Progressive Web App (PWA).

Usage
-----
Install optional web dependencies first::

    pip install "freemocap[web]"

Then start the server::

    freemocap-web                      # default: 0.0.0.0:8000
    freemocap-web --host 0.0.0.0 --port 8080

From an Android device on the same network open Chrome and navigate to::

    http://<server-ip>:8000

"""

import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


def create_app():
    """Create and return the FastAPI application."""
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.staticfiles import StaticFiles
        from fastapi.responses import FileResponse
    except ImportError as exc:
        raise ImportError(
            "FastAPI is required for the web server. "
            'Install it with:  pip install "freemocap[web]"'
        ) from exc

    from freemocap.web_api.routes.recordings import router as recordings_router
    from freemocap.web_api.routes.processing import router as processing_router

    app = FastAPI(
        title="FreeMoCap Web API",
        description=(
            "REST API that wraps the FreeMoCap processing pipeline and "
            "serves the companion PWA for mobile access."
        ),
        version="1.0.0",
    )

    # Allow all origins so that the PWA running on an Android browser (different
    # IP) can reach the server without CORS errors.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(recordings_router, prefix="/api")
    app.include_router(processing_router, prefix="/api")

    # Serve the static PWA files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_pwa():
        return FileResponse(str(_STATIC_DIR / "index.html"))

    # Also serve manifest / service-worker at root level (required by PWA spec)
    @app.get("/manifest.json", include_in_schema=False)
    async def serve_manifest():
        return FileResponse(str(_STATIC_DIR / "manifest.json"))

    @app.get("/sw.js", include_in_schema=False)
    async def serve_sw():
        from fastapi.responses import Response

        sw_path = _STATIC_DIR / "sw.js"
        return Response(
            content=sw_path.read_text(encoding="utf-8"),
            media_type="application/javascript",
        )

    return app


def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the Uvicorn server."""
    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "Uvicorn is required to run the web server. "
            'Install it with:  pip install "freemocap[web]"'
        ) from exc

    app = create_app()
    logger.info(f"Starting FreeMoCap web server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


def main() -> None:
    """CLI entry point: ``freemocap-web``."""
    parser = argparse.ArgumentParser(
        prog="freemocap-web",
        description="Start the FreeMoCap web server / PWA companion app.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
