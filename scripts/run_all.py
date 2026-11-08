"""
Start the whole Smarthack application with one command.

Usage (from anywhere):
    python scripts/run_all.py                 # setup checks, migrations, then every process
    python scripts/run_all.py --skip-migrate  # do not run Flyway
    python scripts/run_all.py --no-web        # backend and workers only
    python scripts/run_all.py --prod          # build the frontend, serve API + SPA on one port

Steps, in order:
    1. `.env` exists (copied from `.env.example` when missing).
    2. Python dependencies are importable; `pip install -e ".[wind,lake,calls]"` runs when they are not.
    3. `frontend/node_modules` exists; `npm install` runs when it does not.
    4. Flyway applies pending migrations (needs `db/flyway.conf` and FLYWAY_PASSWORD in the
       environment or in `.env`). Skipped with a note when Flyway is not configured.
    5. Long-running processes start side by side, with prefixed output:
         api        FastAPI on :8000 (auto-reload)
         web        Vite on :5173, proxying /api to the API
         maintenance  turbine health predictions (runs at start, then on its schedule)
         forecast   7-day park wind forecast, replaced twice a day (runs at start too)
         lake       data lake pipeline: raw/ -> features/ -> predictions/ -> dispatch/ (agent)

Ctrl+C stops everything. If the API or the web server dies, the rest is stopped too.
Only the standard library is used, so this runs before anything is installed.
"""

import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import IO

ROOT = Path(__file__).resolve().parent.parent

#: ANSI colors per process name.
COLORS = {
    "setup": "37",
    "api": "36",
    "web": "35",
    "maintenance": "33",
    "forecast": "32",
    "lake": "34",
}

#: Modules the backend cannot start without; a missing one triggers the pip install.
REQUIRED_MODULES = (
    "fastapi",
    "uvicorn",
    "httpx",
    "dotenv",
    "joblib",
    "catboost",
    "pandas",
    "watchdog",
    "twilio",
    "jinja2",
)

IS_WINDOWS = os.name == "nt"
_print_lock = threading.Lock()


def log(name: str, line: str) -> None:
    """
    Print one prefixed, colored line without interleaving with other threads.

    :param name: Process name, a key of `COLORS`.
    :param line: Text to print.
    """
    color = COLORS.get(name, "37")
    with _print_lock:
        print(f"\033[{color}m{name:<12}\033[0m| {line}", flush=True)


def venv_python() -> str:
    """
    Return the Python interpreter of the project's `.venv`, or the running one.

    :returns path: Path of the interpreter to start children with.
    """
    for candidate in (ROOT / ".venv" / "Scripts" / "python.exe", ROOT / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def read_dotenv() -> dict[str, str]:
    """
    Parse `.env` into a dict (KEY=value lines; quotes stripped; comments ignored).

    :returns values: Variables found in `.env`, empty when the file is missing.
    """
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def run_step(name: str, cmd: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> int:
    """
    Run a command to completion, streaming its output with the process prefix.

    :param name: Prefix for the output lines.
    :param cmd: Command and arguments.
    :param cwd: Working directory.
    :param env: Environment for the child; defaults to the current one.

    :returns code: The command's exit code.
    """
    log(name, "$ " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        log(name, line.rstrip())
    return proc.wait()


def ensure_env_file() -> None:
    """Create `.env` from `.env.example` when missing, and warn about unset Supabase keys."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copyfile(ROOT / ".env.example", env_file)
        log("setup", "created .env from .env.example - fill in SUPABASE_URL and the keys")
    values = read_dotenv()
    url = values.get("SUPABASE_URL", "")
    if not url or "<project-ref>" in url or values.get("SUPABASE_KEY", "") in ("", "changeme"):
        log("setup", "WARNING: SUPABASE_URL / SUPABASE_KEY in .env are placeholders; DB jobs will fail")


def ensure_python_deps(python: str) -> None:
    """
    Install the backend with its `wind`, `lake` and `calls` extras when a required module is missing.

    :param python: Interpreter whose environment is checked and installed into.
    """
    probe = "import importlib.util as u,sys;sys.exit(any(u.find_spec(m) is None for m in %r))"
    missing = subprocess.run([python, "-c", probe % (REQUIRED_MODULES,)]).returncode != 0
    if missing:
        log("setup", "installing Python dependencies (pip install -e .[wind,lake,calls]) ...")
        code = run_step("setup", [python, "-m", "pip", "install", "-e", ".[wind,lake,calls]"])
        if code != 0:
            sys.exit("pip install failed; fix the error above and rerun")
    else:
        log("setup", "Python dependencies OK")


def npm_path() -> str:
    """
    Locate npm, exiting with a hint when Node.js is not on PATH.

    :returns path: Resolved npm executable (`npm.cmd` on Windows).
    """
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("npm not found on PATH. Install Node.js (or activate it, e.g. `fnm use`) and rerun")
    return npm


def ensure_frontend_deps(npm: str) -> None:
    """
    Run `npm install` in `frontend/` when `node_modules` is missing.

    :param npm: Path of the npm executable.
    """
    if (ROOT / "frontend" / "node_modules").is_dir():
        log("setup", "frontend dependencies OK")
        return
    log("setup", "installing frontend dependencies (npm install) ...")
    if run_step("setup", [npm, "install"], cwd=ROOT / "frontend") != 0:
        sys.exit("npm install failed; fix the error above and rerun")


def run_migrations(base_env: dict[str, str]) -> None:
    """
    Apply pending Flyway migrations when Flyway is installed and configured.

    :param base_env: Environment for Flyway (already holds `.env` values, so FLYWAY_PASSWORD
        may live there).
    """
    flyway = shutil.which("flyway")
    conf = ROOT / "db" / "flyway.conf"
    if flyway is None or not conf.exists():
        log("setup", "migrations skipped (needs `flyway` on PATH and db/flyway.conf)")
        return
    if not base_env.get("FLYWAY_PASSWORD"):
        log("setup", "migrations skipped (FLYWAY_PASSWORD is not set in the environment or .env)")
        return
    code = run_step("setup", [flyway, "-configFiles=db/flyway.conf", "migrate"], env=base_env)
    if code != 0:
        sys.exit("flyway migrate failed; fix it, or rerun with --skip-migrate")


class Managed:
    """One long-running child process whose output is streamed with a prefix."""

    def __init__(self, name: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
        """
        Start the process and the thread that forwards its output.

        :param name: Prefix for output lines.
        :param cmd: Command and arguments.
        :param cwd: Working directory.
        :param env: Environment for the child.
        """
        self.name = name
        log(name, "$ " + " ".join(cmd))
        kwargs: dict[str, object] = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,  # type: ignore[arg-type]
        )
        threading.Thread(target=self._pump, args=(self.proc.stdout,), daemon=True).start()

    def _pump(self, stream: IO[str] | None) -> None:
        """
        Forward the child's output line by line.

        :param stream: The child's merged stdout/stderr.
        """
        if stream is None:
            return
        for line in stream:
            log(self.name, line.rstrip())

    def stop(self) -> None:
        """Terminate the process and everything it started (npm and uvicorn spawn children)."""
        if self.proc.poll() is not None:
            return
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass


def parse_args() -> argparse.Namespace:
    """
    Parse command-line options.

    :returns args: Parsed namespace.
    """
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--skip-migrate", action="store_true", help="do not run Flyway")
    p.add_argument("--skip-setup", action="store_true", help="skip dependency checks")
    p.add_argument("--no-web", action="store_true", help="do not start the Vite dev server")
    p.add_argument("--no-workers", action="store_true", help="do not start the background jobs")
    p.add_argument("--prod", action="store_true", help="build the frontend, serve it from the API")
    p.add_argument("--port", type=int, default=8000, help="API port (default 8000)")
    return p.parse_args()


def main() -> int:
    """
    Run the setup steps, start every process and supervise them until Ctrl+C.

    :returns code: Process exit status.
    """
    args = parse_args()
    if IS_WINDOWS:
        os.system("")  # enables ANSI colors in the Windows console
    python = venv_python()

    ensure_env_file()
    env = {**os.environ, **read_dotenv(), "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}

    needs_node = not args.no_web or args.prod
    npm = npm_path() if needs_node else ""
    if not args.skip_setup:
        ensure_python_deps(python)
        if needs_node:
            ensure_frontend_deps(npm)
    if not args.skip_migrate:
        run_migrations(env)
    if args.prod:
        if run_step("setup", [npm, "run", "build"], cwd=ROOT / "frontend") != 0:
            sys.exit("frontend build failed")

    procs: list[Managed] = []
    api_cmd = [python, "-m", "uvicorn", "smarthack.api.app:create_app", "--factory"]
    api_cmd += ["--port", str(args.port)]
    if args.prod:
        env["SMARTHACK_FRONTEND_DIST"] = str(ROOT / "frontend" / "dist")
    else:
        api_cmd.append("--reload")
    procs.append(Managed("api", api_cmd, ROOT, env))
    if not args.prod and not args.no_web:
        procs.append(Managed("web", [npm, "run", "dev"], ROOT / "frontend", env))
    if not args.no_workers:
        job = [python, "-m"]
        procs.append(Managed("maintenance", job + ["smarthack.jobs.maintenance_job", "--every"], ROOT, env))
        procs.append(Managed("forecast", job + ["smarthack.jobs.wind_forecast_job", "--every"], ROOT, env))
        procs.append(Managed("lake", job + ["smarthack.jobs.lake_job", "watch"], ROOT, env))

    web_url = f"http://localhost:{args.port}" if args.prod else "http://localhost:5173"
    log("setup", f"app: {web_url}   api docs: http://localhost:{args.port}/api/docs   (Ctrl+C stops all)")

    code = 0
    try:
        while True:
            for m in procs:
                rc = m.proc.poll()
                if rc is not None:
                    log(m.name, f"exited with code {rc}")
                    if m.name in ("api", "web"):
                        code = rc or 1
                        raise KeyboardInterrupt
            time.sleep(0.5)
    except KeyboardInterrupt:
        log("setup", "stopping all processes ...")
    finally:
        for m in procs:
            m.stop()
        for m in procs:
            try:
                m.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                m.proc.kill()
    return code


if __name__ == "__main__":
    sys.exit(main())
