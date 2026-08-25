"""Offline tests for the stream/thumb/cover-proxy routes (host validation)."""

import asyncio

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.stream.router import image_fetch


class _FakeState:
    def __init__(self, service, settings):
        self.service = service
        self.settings = settings


class _FakeApp:
    def __init__(self, service, settings):
        self.state = _FakeState(service, settings)


class _FakeReq:
    def __init__(self, service, settings):
        self.app = _FakeApp(service, settings)


class _FakeService:
    async def fetch_cover_bytes(self, url):
        return b"\xff\xd8\xff\xe0JPGDATA", "image/jpeg"


def _settings(**kw) -> Settings:
    base = dict(ipb_member_id="1", ipb_pass_hash="abc")
    base.update(kw)
    return Settings(**base)


def _run(req, url):
    return asyncio.run(image_fetch(req, url))


def test_image_fetch_rejects_disallowed_urls():
    req = _FakeReq(_FakeService(), _settings())
    bad = [
        "http://ehgt.org/w/02/597/x.webp",  # not https
        "https://evil.com/x.webp",  # not a cover host
        "https://exhentai.org/w/02/597/x.webp",  # page host, not the s.* cover host
        "https://ehgt.org.evil.com/x.webp",  # suffix trick
    ]
    for url in bad:
        with pytest.raises(HTTPException) as ei:
            _run(req, url)
        assert ei.value.status_code == 400, url


def test_image_fetch_allows_cover_hosts():
    req = _FakeReq(_FakeService(), _settings())
    for url in [
        "https://ehgt.org/w/02/597/37188-uwng9q95.webp",
        "https://s.exhentai.org/w/02/597/37188-uwng9q95.webp",
    ]:
        resp = _run(req, url)
        assert resp.body == b"\xff\xd8\xff\xe0JPGDATA"
        assert resp.media_type == "image/jpeg"


def test_image_fetch_allowlist_configurable():
    req = _FakeReq(
        _FakeService(), _settings(image_proxy_hosts=("cdn.example.com",))
    )
    # configured host is allowed
    resp = _run(req, "https://cdn.example.com/w/02/597/x.webp")
    assert resp.status_code == 200
    # default host no longer allowed after override
    with pytest.raises(HTTPException) as ei:
        _run(req, "https://ehgt.org/w/02/597/x.webp")
    assert ei.value.status_code == 400
