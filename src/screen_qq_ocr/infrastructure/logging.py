import logging
from logging.handlers import RotatingFileHandler


def configure_logging(folder):
    folder.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("screen_qq_ocr")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(
            folder / "events.log", maxBytes=5 * 1024 * 1024, backupCount=4, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger
