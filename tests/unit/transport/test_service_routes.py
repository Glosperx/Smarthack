"""Unit tests for the transport network service files and API routes."""

import gzip
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from tests.conftest import skip_module_without_extra

skip_module_without_extra("transport")

from smarthack.api.app import create_app  # noqa: E402
from smarthack.services import transport_service  # noqa: E402
from smarthack.transport import constants as C  # noqa: E402
from smarthack.transport.network import Road  # noqa: E402


def _roads() -> list[Road]:
    """Two short roads with verdicts: one viable, one blocked."""
    a = Road(0, 0, "A2", [1, 2], [44.0, 44.0], [28.0, 28.01], C.VERDICT_VIABLE)
    b = Road(4, 1, "", [2, 3], [44.0, 44.0], [28.01, 28.02], C.VERDICT_BLOCKED)
    return [a, b]


def test_encode_network_packs_roads() -> None:
    """Each road becomes [class, verdict, reasons, ref index, flat coordinates]."""
    network = transport_service.encode_network(_roads())
    assert network["classes"] == list(C.ROAD_CLASSES)
    assert network["refs"] == ["A2"]
    assert network["roads"][0] == [0, C.VERDICT_VIABLE, 0, 0, [44.0, 28.0, 44.0, 28.01]]
    assert network["roads"][1][3] == -1


def test_summarise_counts_kilometres_per_verdict_and_reason() -> None:
    """Kilometres add up per verdict, and a blocking reason is marked as such."""
    summary = transport_service.summarise(_roads(), None, drawn=2)
    km = {v.code: v.km for v in summary.verdicts}
    assert km[C.VERDICT_VIABLE] == pytest.approx(0.8, abs=0.05)
    assert km[C.VERDICT_BLOCKED] == pytest.approx(0.8, abs=0.05)
    height = next(r for r in summary.reasons if r.bit == 1)
    assert height.blocking and height.km > 0


@pytest.fixture
def built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A network directory with files written the way `build_network` writes them."""
    monkeypatch.setenv("TRANSPORT_NETWORK_DIR", str(tmp_path))
    summary = transport_service.summarise(_roads(), None, drawn=2)
    (tmp_path / "summary.json").write_text(summary.model_dump_json(), encoding="utf-8")
    payload = json.dumps(transport_service.encode_network(_roads())).encode()
    (tmp_path / "network.json.gz").write_bytes(gzip.compress(payload))
    return tmp_path


def test_routes_serve_the_built_network(built: Path) -> None:
    """Summary is JSON; the network arrives gzipped and decodes to the packed layout."""
    client = TestClient(create_app())
    summary = client.get("/api/transport/summary")
    assert summary.status_code == 200
    assert summary.json()["road_count"] == 2
    network = client.get("/api/transport/network")
    assert network.status_code == 200
    assert network.headers["content-encoding"] == "gzip"
    assert len(network.json()["roads"]) == 2  # httpx undoes the gzip, like a browser


def test_routes_answer_503_before_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With nothing built, both endpoints say how to build it."""
    monkeypatch.setenv("TRANSPORT_NETWORK_DIR", str(tmp_path))
    client = TestClient(create_app())
    for path in ("/api/transport/summary", "/api/transport/network"):
        resp = client.get(path)
        assert resp.status_code == 503
        assert "make transport" in resp.json()["detail"]
