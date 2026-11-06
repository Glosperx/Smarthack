"""
# Entry point

`python -m smarthack`, and what the Docker image runs. It configures logging,
reports what it started with, and returns: replace the body of `main` with the
application when it exists. Nothing imports this module.

The following can be imported from this module:
- `main`
"""

import logging
import sys

from smarthack import __version__
from smarthack.config import app_env
from smarthack.constants import APP_NAME
from smarthack.utils.logging_utils import configure_logging

logger = logging.getLogger(__name__)


def main() -> int:
    """
    Start the application.

    :returns code: The process exit code; 0 on a clean run.
    """
    configure_logging()
    logger.info("%s %s started in the %s environment", APP_NAME, __version__, app_env())
    return 0


__all__ = ["main"]

if __name__ == "__main__":
    sys.exit(main())
