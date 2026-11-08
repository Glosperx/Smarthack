"""
# Decision model server

Serves one decision model over HTTP in the System One format, so the dispatch agent can ask it a
`choice` question and get a probability for every option. It runs natively on the Mac, with the
model on MPS: Docker on a Mac cannot see the Metal GPU.

    POST /v1/systemone   {"state": ..., "questions": {"q": {"type": "choice", ...}}}
                         -> {"answers": {"q": {"probabilities": {option: p}}}}
    GET  /health         -> {"status": "ok", "model": "jeffan-4b"}

Answers: 400 for a body that is not the agreed shape, 413 for one over a megabyte, 422 for a
question that is not a `choice` (the only type any adapter answers), 404 and 405 elsewhere. Each
question costs one forward pass, and passes run one at a time behind a lock: one model, one GPU,
and a second pass in parallel would only be slower.

The server binds to the loopback address by default. The requests carry turbine data and nothing
here authenticates a caller, so it is not meant to be reachable from the network.

It imports nothing from `smarthack`: this experiment has its own environment. The agent's client
(`smarthack/clients/decision_client.py`) is the other half of the contract.

Run from `experiments/decision_model`:

    uv run python -I -m decision_model.server
    uv run python -I -m decision_model.server --port 8766 --device cpu

The following can be imported from this module:
- `BadRequest`
- `UnsupportedQuestion`
- `answer`
- `make_server`
- `main`
"""

import argparse
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import threading
import time
from typing import Any

from decision_model.adapters import Adapter, load_adapter

logger = logging.getLogger("decision_model.server")

HOST = "127.0.0.1"
PORT = 8765
MAX_BODY_BYTES = 1_000_000
ENDPOINT = "/v1/systemone"


class BadRequest(ValueError):
    """The body is not shaped as the format says: answered with 400."""


class UnsupportedQuestion(ValueError):
    """The question is well formed but of a type no adapter answers: answered with 422."""


def _question(key: str, raw: Any) -> dict[str, Any]:
    """
    Check one question.

    :param key: The question's key in `questions`.
    :param raw: The question as decoded.

    :returns question: The question, known to be a `choice` with instructions and options.
    :raises BadRequest: When it is not an object, or lacks `type`, `instructions` or `criteria`.
    :raises UnsupportedQuestion: When `type` is not `choice`.
    """
    if not isinstance(raw, dict):
        raise BadRequest(f"question {key!r} is not an object")
    kind = raw.get("type")
    if not isinstance(kind, str):
        raise BadRequest(f"question {key!r} has no type")
    if kind != "choice":
        raise UnsupportedQuestion(f"question {key!r} is of type {kind!r}; only 'choice' is served")
    if not isinstance(raw.get("instructions"), str):
        raise BadRequest(f"question {key!r} has no instructions")
    criteria = raw.get("criteria")
    if not isinstance(criteria, dict) or not criteria:
        raise BadRequest(f"question {key!r} has no options")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in criteria.items()):
        raise BadRequest(f"the options of question {key!r} are not text")
    if len(criteria) > 26:
        raise BadRequest(f"question {key!r} has more than 26 options")
    return raw


def answer(adapter: Adapter, payload: Any) -> dict[str, Any]:
    """
    Answer a System One request, one forward pass per question.

    :param adapter: The loaded model.
    :param payload: The decoded body.

    :returns response: `{"answers": {key: {"probabilities": {option: p}}}}`.
    :raises BadRequest: When the body is not an object with a `state` and a non-empty `questions`.
    :raises UnsupportedQuestion: When a question is not a `choice`.
    """
    if not isinstance(payload, dict):
        raise BadRequest("the body is not an object")
    if "state" not in payload or not isinstance(payload["state"], (dict, str)):
        raise BadRequest("the body has no state")
    questions = payload.get("questions")
    if not isinstance(questions, dict) or not questions:
        raise BadRequest("the body has no questions")
    checked = {key: _question(key, raw) for key, raw in questions.items()}
    answers: dict[str, Any] = {}
    for key, question in checked.items():
        request = {"state": payload["state"], "questions": {key: question}}
        answers[key] = {"probabilities": adapter.choice(request)}
    return {"answers": answers}


def make_server(adapter: Adapter, host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    """
    Build the server around a loaded model; it does not start serving.

    :param adapter: The loaded model.
    :param host: Address to bind.
    :param port: Port to bind; 0 lets the system pick a free one.

    :returns server: Call `serve_forever()` on it, `shutdown()` to stop.
    """
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        """One request: `GET /health` or `POST /v1/systemone`."""

        def _send(self, status: int, body: Mapping[str, Any]) -> None:
            """Write a JSON response."""
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            """Answer the health check."""
            if self.path == "/health":
                self._send(200, {"status": "ok", "model": adapter.name})
            elif self.path == ENDPOINT:
                self._send(405, {"error": "use POST"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            """Answer a System One request."""
            if self.path != ENDPOINT:
                self._send(405 if self.path == "/health" else 404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send(400, {"error": "Content-Length is required"})
                return
            if length <= 0:
                self._send(400, {"error": "the body is empty"})
                return
            if length > MAX_BODY_BYTES:
                self._send(413, {"error": f"the body is over {MAX_BODY_BYTES} bytes"})
                return
            try:
                payload = json.loads(self.rfile.read(length))
            except ValueError:
                self._send(400, {"error": "the body is not JSON"})
                return
            started = time.perf_counter()
            try:
                with lock:
                    response = answer(adapter, payload)
            except BadRequest as exc:
                self._send(400, {"error": str(exc)})
                return
            except UnsupportedQuestion as exc:
                self._send(422, {"error": str(exc)})
                return
            except Exception:
                logger.exception("the model failed on a request")
                self._send(500, {"error": "the model failed"})
                return
            logger.info("answered in %.0f ms", 1000 * (time.perf_counter() - started))
            self._send(200, response)

        def log_message(self, format: str, *args: Any) -> None:
            """Send the access log to `logging` instead of stderr."""
            logger.debug(format, *args)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    """
    Load the model, warm it up and serve until interrupted.

    :param argv: Arguments; None reads `sys.argv`.

    :returns status: 0 after a clean stop.
    """
    parser = argparse.ArgumentParser(description="Serve a decision model in the System One format.")
    parser.add_argument("--model", default="jeffan-4b")
    parser.add_argument("--device", default="mps", choices=["mps", "cpu"])
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        logger.warning("binding to %s: the server has no authentication", args.host)
    started = time.perf_counter()
    adapter = load_adapter(args.model, args.device)
    logger.info("loaded %s in %.1f s", args.model, time.perf_counter() - started)
    # The first forward pass compiles kernels and is several times slower than the next ones.
    answer(
        adapter,
        {
            "state": {"warm_up": True},
            "questions": {
                "q": {
                    "type": "choice",
                    "instructions": "Pick one.",
                    "criteria": {"a": "A", "b": "B"},
                }
            },
        },
    )
    server = make_server(adapter, args.host, args.port)
    logger.info("serving %s on http://%s:%d%s", args.model, args.host, args.port, ENDPOINT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("stopping")
    finally:
        server.server_close()
    return 0


__all__ = ["BadRequest", "UnsupportedQuestion", "answer", "make_server", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
