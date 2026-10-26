import pytest
from fastapi.testclient import TestClient

import app.main as main
from tests.conftest import DEFAULT_PRICES, FakeMarketSource, StubPriceCache


@pytest.fixture
def static_client(db_path, tmp_path, monkeypatch):
    static = tmp_path / "static"
    (static / "_next" / "static").mkdir(parents=True)
    (static / "index.html").write_text("<html>home</html>")
    (static / "about.html").write_text("<html>about</html>")
    (static / "docs").mkdir()
    (static / "docs" / "index.html").write_text("<html>docs</html>")
    (static / "_next" / "static" / "app.js").write_text("console.log('hi')")
    (tmp_path / "secret.txt").write_text("secret")

    monkeypatch.setenv("FINALLY_STATIC_DIR", str(static))
    monkeypatch.setattr(main, "PriceCache", lambda: StubPriceCache(DEFAULT_PRICES))
    monkeypatch.setattr(main, "create_market_data_source", FakeMarketSource)
    with TestClient(main.create_app()) as client:
        yield client


def test_root_serves_index(static_client):
    response = static_client.get("/")
    assert response.status_code == 200
    assert response.text == "<html>home</html>"
    assert response.headers["content-type"].startswith("text/html")


def test_exact_asset(static_client):
    response = static_client.get("/_next/static/app.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_html_and_directory_index_resolution(static_client):
    assert static_client.get("/about").text == "<html>about</html>"
    assert static_client.get("/docs").text == "<html>docs</html>"
    assert static_client.get("/docs/").text == "<html>docs</html>"


def test_unknown_page_falls_back_to_index(static_client):
    response = static_client.get("/some/client/route")
    assert response.status_code == 200
    assert response.text == "<html>home</html>"


def test_missing_asset_is_404(static_client):
    assert static_client.get("/_next/static/missing.js").status_code == 404


def test_path_traversal_blocked(static_client):
    response = static_client.get("/..%2Fsecret.txt")
    assert response.status_code == 404
    assert "secret" not in response.text


def test_api_routes_win_and_api_404_stays_json(static_client):
    assert static_client.get("/api/health").json() == {"status": "ok"}
    response = static_client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_no_static_dir_means_no_catch_all(client):
    assert client.get("/").status_code == 404
