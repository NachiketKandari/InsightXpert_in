"""Logging configuration for InsightXpert.

Call setup_logging() once at the CLI entry point (main()). Every other module
simply does `logger = logging.getLogger(__name__)` and logs away.

Two handlers are set up:
- stderr  — INFO and above, human-readable, for live monitoring
- file    — DEBUG and above, written to logs/insightxpert_<timestamp>.log

Log format (both handlers):
    HH:MM:SS  LEVEL     module.path              funcName:lineno  message

Stdout stays clean for data output (JSON dumps, query results) that callers
may pipe to other tools.
"""
import logging
import sys
from datetime import datetime
from pathlib import Path


_STDERR_FMT = "%(asctime)s  %(levelname)-8s  %(name)-42s  %(funcName)s:%(lineno)d  %(message)s"
_DATE_FMT_SHORT = "%H:%M:%S"
_DATE_FMT_FULL = "%Y-%m-%d %H:%M:%S"

_current_log_file: Path | None = None


def current_log_file() -> Path | None:
    """Return the path of the log file opened by setup_logging(), or None."""
    return _current_log_file


def rename_log(new_path: Path) -> None:
    """Close the file handler, rename the log file, reopen at the new path.

    Intended to be called at the end of a run once the final outcome is known
    (e.g. after evaluate completes and accuracy is available).
    """
    global _current_log_file
    root = logging.getLogger()

    file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
    for fh in file_handlers:
        fh.close()
        root.removeHandler(fh)

    if _current_log_file and _current_log_file.exists():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        _current_log_file.rename(new_path)
        _current_log_file = new_path

    new_fh = logging.FileHandler(new_path, encoding="utf-8")
    new_fh.setLevel(logging.DEBUG)
    new_fh.setFormatter(logging.Formatter(fmt=_STDERR_FMT, datefmt=_DATE_FMT_FULL))
    root.addHandler(new_fh)


def setup_logging(level: int = logging.DEBUG, tag: str = "") -> Path:
    """Configure root logger with a stderr handler and a rotating file handler.

    Returns the path of the log file created for this run.
    Safe to call multiple times — subsequent calls replace handlers (force=True).

    tag: optional run identifier (e.g. "evaluate-toxicology-nolink") prepended to
         the filename so logs are self-describing without manual renaming.
    """
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    stem = f"{tag}_" if tag else ""
    log_file = logs_dir / f"{stem}{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # stderr: INFO+ with short timestamp
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.INFO)
    stderr_handler.setFormatter(logging.Formatter(fmt=_STDERR_FMT, datefmt=_DATE_FMT_SHORT))

    # file: DEBUG+ with full timestamp
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(fmt=_STDERR_FMT, datefmt=_DATE_FMT_FULL))

    logging.basicConfig(level=level, handlers=[stderr_handler, file_handler], force=True)

    # Third-party libraries inherit the root DEBUG level and spam INFO logs on
    # every API call. Pin them to WARNING so only actual errors surface.
    for noisy in ("google_genai", "httpx", "urllib3", "google.auth"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    global _current_log_file
    _current_log_file = log_file
    logging.getLogger(__name__).debug("Log file: %s", log_file.resolve())
    return log_file
