from pathlib import Path

from loguru import logger

logger.add(sink="log.txt")

DUMP_DIR = Path("__dump__")
DUMP_DIR.mkdir(exist_ok=True)

WORK_DIR = Path("./__workdir__")
WORK_DIR.mkdir(exist_ok=True)

DATABASE_CONNECTION = "sqlite:///database.sqlite3"
