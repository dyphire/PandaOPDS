"""Gallery rating proxy API."""

from __future__ import annotations

import math
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["rating"])
_GALLERY_PATH = re.compile(r"^/g/(\d+)/([0-9a-fA-F]+)/?$")


def _gallery_from_url(value: object, host: str) -> tuple[int, str]:
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail="'url' must be a gallery URL")
    try:
        parsed = urlsplit(value)
        # Reject credentials, ports, fragments, non-https schemes and host tricks.
        if (parsed.scheme.lower() != "https" or parsed.hostname != host
                or parsed.username is not None or parsed.password is not None
                or parsed.port is not None or parsed.fragment):
            raise ValueError
        match = _GALLERY_PATH.fullmatch(parsed.path)
        if match is None:
            raise ValueError
        return int(match.group(1)), match.group(2)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="'url' must be an official gallery URL for the configured site")


def _applied_score(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=400, detail="'rating' must be a finite number from 0.1 to 5.0")
    try:
        score = float(value)
    except (OverflowError, ValueError):
        raise HTTPException(status_code=400, detail="'rating' must be a finite number from 0.1 to 5.0")
    if not math.isfinite(score) or not 0.1 <= score <= 5.0:
        raise HTTPException(status_code=400, detail="'rating' must be a finite number from 0.1 to 5.0")
    return max(0.5, min(5.0, math.floor(score * 2 + 0.5) / 2))


@router.post("/api/rating")
async def rate_gallery(request: Request, payload: dict):
    settings = request.app.state.settings
    if not (settings.ipb_member_id and settings.ipb_pass_hash):
        raise HTTPException(status_code=403, detail="rating requires IPB cookies (IPB_MEMBER_ID + IPB_PASS_HASH)")
    gid, token = _gallery_from_url(payload.get("url"), settings.site_host)
    score = _applied_score(payload.get("rating"))
    result = await request.app.state.service.rate_gallery(gid, token, score)
    return {"gid": gid, "token": token, "rating": score, **result}
