import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.eh.service import EHService
from app.rating.router import _applied_score, _gallery_from_url
from app.rating.router import router


@pytest.mark.parametrize(("url", "expected"), [
    ("https://e-hentai.org/g/123/AbCd/", (123, "AbCd")),
    ("https://e-hentai.org/g/123/AbCd?x=1", (123, "AbCd")),
])
def test_gallery_url_parse(url, expected):
    assert _gallery_from_url(url, "e-hentai.org") == expected


@pytest.mark.parametrize("url", [
    "http://e-hentai.org/g/1/abc/", "https://evil.test/g/1/abc/",
    "https://e-hentai.org.evil.test/g/1/abc/", "https://e-hentai.org/gallery/1/abc",
    "https://e-hentai.org/g/1/abc/extra", "https://user@e-hentai.org/g/1/abc/",
])
def test_gallery_url_rejects_invalid(url):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _gallery_from_url(url, "e-hentai.org")


@pytest.mark.parametrize(("score", "expected"), [(0.1, 0.5), (0.25, 0.5), (0.26, 0.5), (0.75, 1.0), (4.9, 5.0), (5, 5.0)])
def test_score_mapping(score, expected):
    assert _applied_score(score) == expected


@pytest.mark.parametrize("score", [0, 5.01, -1, float("nan"), float("inf"), True, "3"])
def test_score_bounds(score):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _applied_score(score)


def test_score_bounds_large_integer():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        _applied_score(10**1000)


class RatingClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    async def establish_session(self):
        pass

    async def close(self):
        pass

    async def post_api(self, payload):
        self.payloads.append(payload)
        return json.dumps(self.responses.pop(0))


@pytest.mark.asyncio
async def test_rating_service_payload_and_key_refresh(tmp_path, monkeypatch):
    settings = Settings(ipb_member_id="44", ipb_pass_hash="secret", cache_dir=tmp_path)
    client = RatingClient([{"error": "Invalid API key"}, {"rating_usr": 4.5, "rating_avg": 4.12, "rating_cnt": 22}])
    service = EHService(settings, client=client)
    pages = iter(['<script>var apikey = "oldkey";</script>', '<script>var apikey = "freshkey";</script>'])
    async def page(path, params=None):
        assert path == "/g/123/abc/"
        return next(pages)
    monkeypatch.setattr(service, "_html_get", page)
    try:
        result = await service.rate_gallery(123, "abc", 4.5)
    finally:
        await service.close()
    assert result == {"rating_usr": 4.5, "rating_avg": 4.12, "rating_cnt": 22}
    assert [p["apikey"] for p in client.payloads] == ["oldkey", "freshkey"]
    assert client.payloads[1] == {
        "method": "rategallery", "apikey": "freshkey", "apiuid": 44,
        "gid": 123, "token": "abc", "rating": 9,
    }


@pytest.mark.asyncio
async def test_rating_service_retries_when_response_fields_are_missing(tmp_path, monkeypatch):
    settings = Settings(ipb_member_id="44", ipb_pass_hash="secret", cache_dir=tmp_path)
    client = RatingClient([{}, {"rating_usr": 4.5, "rating_avg": 4.12, "rating_cnt": 22}])
    service = EHService(settings, client=client)
    pages = iter(['<script>var apikey = "oldkey";</script>', '<script>var apikey = "freshkey";</script>'])

    async def page(path, params=None):
        assert path == "/g/123/abc/"
        return next(pages)

    monkeypatch.setattr(service, "_html_get", page)
    try:
        result = await service.rate_gallery(123, "abc", 4.5)
    finally:
        await service.close()

    assert result["rating_usr"] == 4.5
    assert [p["apikey"] for p in client.payloads] == ["oldkey", "freshkey"]


def test_endpoint_requires_ipb_and_returns_result(monkeypatch):
    test_app = FastAPI()
    test_app.include_router(router)
    test_app.state.settings = Settings(ipb_member_id="44", ipb_pass_hash="secret")
    class Service:
        async def rate_gallery(self, gid, token, rating):
            assert (gid, token, rating) == (123, "abc", 4.5)
            return {"rating_usr": 4.5, "rating_avg": 4.12, "rating_cnt": 22}
    test_app.state.service = Service()
    with TestClient(test_app) as client:
        response = client.post("/api/rating", json={"url": "https://e-hentai.org/g/123/abc", "rating": 4.5})
        assert response.status_code == 200
        assert response.json()["rating"] == 4.5
        test_app.state.settings = Settings()
        response = client.post("/api/rating", json={"url": "https://e-hentai.org/g/123/abc", "rating": 4.5})
        assert response.status_code == 403
