import logging

logger = logging.getLogger("plane_bot")


def configure_logging(mode="INFO"):
    level = logging.DEBUG if mode.upper() == "DEBUG" else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for name in ("httpx", "httpcore", "telegram", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
