"""
# Entry point

`python -m smarthack`, launching the Uvicorn web server and serving
the FastAPI application and the built React frontend.

The following can be imported from this module:
- `main`
"""

import logging
import os
import sys

import uvicorn

from smarthack import __version__, config
from smarthack.constants import APP_NAME
from smarthack.utils.logging_utils import configure_logging

logger = logging.getLogger(__name__)


def main(serve: bool | None = None) -> int:
    """
    Start the application server.

    :param serve: Whether to launch the Uvicorn HTTP server. Defaults to
        True unless running under pytest or `--no-serve` is passed.

    :returns code: The process exit code; 0 on a clean run.
    """
    configure_logging()
    logger.info("%s %s started in the %s environment", APP_NAME, __version__, config.app_env())

    if serve is None:
        in_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        serve = not in_test and "--no-serve" not in sys.argv

    if serve:
        uvicorn.run(
            "smarthack.api.app:create_app",
            factory=True,
            host=config.host(),
            port=config.port(),
            log_level=config.log_level().lower(),
        )
    return 0


__all__ = ["main"]

if __name__ == "__main__":
    sys.exit(main())
