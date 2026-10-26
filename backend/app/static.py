"""Serve the Next.js static export from the same origin as the API."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse


def create_static_router(static_dir: Path) -> APIRouter:
    """Catch-all router for non-API paths. Register it after every API route.

    Resolution order for `/foo`: `foo` (exact file), `foo.html`, `foo/index.html`,
    then `index.html` so client-side routes still load the app. Missing assets (paths with
    a file extension) 404 instead of falling back. `/api/*` stays a JSON 404.
    """
    root = static_dir.resolve()
    router = APIRouter(include_in_schema=False)

    def resolve(path: str) -> Path | None:
        candidates = [root / path, root / f"{path}.html", root / path / "index.html"] if path else []
        if "." not in path.rsplit("/", 1)[-1]:
            candidates.append(root / "index.html")
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                return candidate
        return None

    @router.api_route("/{path:path}", methods=["GET", "HEAD"])
    async def static_file(path: str) -> FileResponse:
        path = path.strip("/")
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        file = resolve(path)
        if file is None:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(file)

    return router
