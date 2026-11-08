import ast
from collections.abc import Iterator, Mapping
import json
from pathlib import Path
import threading
import time
from typing import Any
import urllib.error
import urllib.request

import pytest

from decision_model import server
from decision_model.server import make_server

QUESTION = {
    "type": "choice",
    "instructions": "Which?",
    "criteria": {"a": "Option A.", "b": "Option B."},
}


class FakeAdapter:
    """Answers 0.75 / 0.25, remembers each request, and measures how many forwards overlap."""

    name = "fake-model"

    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.requests: list[Mapping[str, Any]] = []
        self.delay = delay
        self.fail = fail
        self.running = 0
        self.most_running = 0
        self._guard = threading.Lock()

    def choice(self, request: Mapping[str, Any]) -> dict[str, float]:
        with self._guard:
            self.running += 1
            self.most_running = max(self.most_running, self.running)
        try:
            time.sleep(self.delay)
            if self.fail:
                raise RuntimeError("out of memory")
            self.requests.append(request)
            keys = list(next(iter(request["questions"].values()))["criteria"])
            return {k: (0.75 if i == 0 else 0.25 / (len(keys) - 1)) for i, k in enumerate(keys)}
        finally:
            with self._guard:
                self.running -= 1


class Running:
    """A server on a free port, in a thread."""

    def __init__(self, adapter: FakeAdapter) -> None:
        self.adapter = adapter
        self.httpd = make_server(adapter, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(
            target=lambda: self.httpd.serve_forever(poll_interval=0.01), daemon=True
        )
        self.thread.start()

    def call(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        request = urllib.request.Request(self.url + path, data=body, method=method)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def post(self, payload: Any) -> tuple[int, Any]:
        return self.call("POST", "/v1/systemone", json.dumps(payload).encode())

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def running() -> Iterator[Running]:
    instance = Running(FakeAdapter())
    yield instance
    instance.stop()


def test_health_names_the_model(running: Running) -> None:
    assert running.call("GET", "/health") == (200, {"status": "ok", "model": "fake-model"})


def test_a_choice_question_gets_one_probability_per_option(running: Running) -> None:
    status, body = running.post({"state": {"park_id": "p"}, "questions": {"q": QUESTION}})

    assert status == 200
    assert body == {"answers": {"q": {"probabilities": {"a": 0.75, "b": 0.25}}}}
    assert running.adapter.requests == [{"state": {"park_id": "p"}, "questions": {"q": QUESTION}}]


def test_each_question_costs_one_forward_pass(running: Running) -> None:
    other = {**QUESTION, "criteria": {"x": "X.", "y": "Y.", "z": "Z."}}

    status, body = running.post({"state": "text state", "questions": {"q1": QUESTION, "q2": other}})

    assert status == 200
    assert set(body["answers"]) == {"q1", "q2"}
    assert [list(r["questions"]) for r in running.adapter.requests] == [["q1"], ["q2"]]
    assert all(r["state"] == "text state" for r in running.adapter.requests)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(["not", "an", "object"], id="not-an-object"),
        pytest.param({"questions": {"q": QUESTION}}, id="no-state"),
        pytest.param({"state": 5, "questions": {"q": QUESTION}}, id="state-is-a-number"),
        pytest.param({"state": {}}, id="no-questions"),
        pytest.param({"state": {}, "questions": {}}, id="empty-questions"),
        pytest.param({"state": {}, "questions": {"q": "text"}}, id="question-is-text"),
        pytest.param({"state": {}, "questions": {"q": {"instructions": "?"}}}, id="no-type"),
        pytest.param(
            {"state": {}, "questions": {"q": {"type": "choice", "criteria": {"a": "A"}}}},
            id="no-instructions",
        ),
        pytest.param(
            {"state": {}, "questions": {"q": {"type": "choice", "instructions": "?"}}},
            id="no-options",
        ),
        pytest.param(
            {"state": {}, "questions": {"q": {**QUESTION, "criteria": {}}}}, id="empty-options"
        ),
        pytest.param(
            {"state": {}, "questions": {"q": {**QUESTION, "criteria": {"a": 1}}}},
            id="option-is-not-text",
        ),
        pytest.param(
            {
                "state": {},
                "questions": {
                    "q": {
                        **QUESTION,
                        "criteria": {chr(97 + i): "x" for i in range(26)} | {"zz": "x"},
                    }
                },
            },
            id="too-many-options",
        ),
    ],
)
def test_a_malformed_body_is_a_400_and_the_model_is_not_run(running: Running, payload: Any) -> None:
    status, body = running.post(payload)

    assert status == 400
    assert "error" in body
    assert running.adapter.requests == []


def test_a_body_that_is_not_json_is_a_400(running: Running) -> None:
    assert running.call("POST", "/v1/systemone", b"{not json")[0] == 400


def test_an_empty_body_is_a_400(running: Running) -> None:
    assert running.call("POST", "/v1/systemone", b"")[0] == 400


def test_a_declared_body_over_the_limit_is_a_413_without_reading_it(running: Running) -> None:
    headers = {"Content-Length": str(server.MAX_BODY_BYTES + 1)}

    status, body = running.call("POST", "/v1/systemone", b"{}", headers)

    assert status == 413
    assert "error" in body
    assert running.adapter.requests == []


def test_a_question_that_is_not_a_choice_is_a_422(running: Running) -> None:
    number = {"type": "number", "instructions": "How many?"}

    status, body = running.post({"state": {}, "questions": {"q": number}})

    assert status == 422
    assert "choice" in body["error"]
    assert running.adapter.requests == []


def test_one_bad_question_stops_the_whole_request_before_any_forward_pass(
    running: Running,
) -> None:
    status, _ = running.post(
        {
            "state": {},
            "questions": {"good": QUESTION, "bad": {"type": "number", "instructions": "?"}},
        }
    )

    assert status == 422
    assert running.adapter.requests == []


def test_unknown_paths_and_wrong_methods(running: Running) -> None:
    assert running.call("GET", "/nope")[0] == 404
    assert running.call("POST", "/nope", b"{}")[0] == 404
    assert running.call("GET", "/v1/systemone")[0] == 405
    assert running.call("POST", "/health", b"{}")[0] == 405


def test_a_model_failure_is_a_500_and_the_server_keeps_serving() -> None:
    instance = Running(FakeAdapter(fail=True))
    try:
        assert instance.post({"state": {}, "questions": {"q": QUESTION}})[0] == 500
        assert instance.call("GET", "/health")[0] == 200
    finally:
        instance.stop()


def test_forward_passes_never_overlap_under_concurrent_requests() -> None:
    adapter = FakeAdapter(delay=0.05)
    instance = Running(adapter)
    statuses: list[int] = []

    def ask() -> None:
        statuses.append(instance.post({"state": {}, "questions": {"q": QUESTION}})[0])

    try:
        threads = [threading.Thread(target=ask) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        instance.stop()

    assert statuses == [200] * 5
    assert adapter.most_running == 1
    assert len(adapter.requests) == 5


def test_the_server_binds_to_the_loopback_address_by_default() -> None:
    assert server.HOST == "127.0.0.1"
    assert server.PORT == 8765


def test_the_server_never_imports_the_application() -> None:
    tree = ast.parse(Path(server.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert "smarthack" not in imported
