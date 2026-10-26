from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import uvicorn
from alembic.config import Config

from alembic import command
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.backup import restore_database_if_needed


def migrate() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    command.upgrade(config, "head")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.validate_runtime_secrets()
    restore_database_if_needed(settings)
    migrate()

    worker = subprocess.Popen([sys.executable, "-m", "app.worker"])
    try:
        port = int(os.environ.get("_FAAS_RUNTIME_PORT", os.environ.get("PORT", "8000")))
        uvicorn.run("app.main:app", host="0.0.0.0", port=port, proxy_headers=True)
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=5)


if __name__ == "__main__":
    main()
