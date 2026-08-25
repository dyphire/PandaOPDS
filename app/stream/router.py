"""PSE stream + thumbnail proxy routes.

- GET /stream/{gid}/{token}/page/{n}  (n is 0-based per OPDS-PSE)
- GET /image/{gid}/{token}/thumb
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..eh.exceptions import EHException, ExceedLimitError
from ..eh.service import EHService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])

# images are immutable per (gid, token, page): long public cache
_IMAGE_CACHE = "public, max-age=604800"


def _service(request: Request) -> EHService:
    return request.app.state.service


@router.get("/stream/{gid}/{token}/page/{page}")
async def stream_page(request: Request, gid: int, token: str, page: int):
    service = _service(request)
    settings = request.app.state.settings
    base = settings.pse_page_base
    if page < base:
        raise HTTPException(
            status_code=400,
            detail=f"page must be >= {base} (PSE page base)",
        )
    try:
        data, mime = await service.get_image(gid, token, page)
    except ExceedLimitError as exc:
        # image quota exhausted: tell the client how long to back off (the
        # same horizon the circuit breaker uses for exceedLimit trips)
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(int(settings.exceed_cooldown_seconds))},
        ) from exc
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": _IMAGE_CACHE},
    )


@router.get("/image/{gid}/{token}/thumb")
async def thumb(request: Request, gid: int, token: str):
    service = _service(request)
    data, mime = await service.get_thumb(gid, token)
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": _IMAGE_CACHE},
    )


# Standard-cover CDN hosts allowed through /image/fetch (comment covers) come
# from settings.image_proxy_hosts (configurable via IMAGE_PROXY_HOSTS, defaults
# to the two cover CDNs). Restricting the host keeps the proxy from becoming
# an open one; see config.image_proxy_hosts for the default.

_COVER_PROXY_ERRORS = {"Cache-Control": "no-store"}


@router.get("/image/fetch")
async def image_fetch(request: Request, url: str):
    """Proxy a cover/preview URL (settings.image_proxy_hosts) same-origin.

    Comment content (x:reviews) may embed eh/ex cover images on a different
    origin; a web client fetching them cross-origin hits CORS. This endpoint
    fetches the exact bytes through the throttled, authenticated client and
    serves them from the PandaOPDS origin. The URL is treated as opaque (no
    gid/token parsing).
    """
    settings = request.app.state.settings
    service = _service(request)
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc.lower() not in settings.image_proxy_hosts_set:
        raise HTTPException(status_code=400, detail="unsupported image url")
    try:
        data, mime = await service.fetch_cover_bytes(url)
    except ExceedLimitError as exc:
        raise HTTPException(
            status_code=429, detail=str(exc), headers=_COVER_PROXY_ERRORS
        ) from exc
    except EHException as exc:
        logger.warning("cover proxy fetch failed url=%s error=%s", url, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": _IMAGE_CACHE},
    )
