import logging
import sys


def setup_logger(name='project', level=logging.INFO):
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger(name)
    logger.setLevel(level)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    logger.handlers.clear()
    logger.addHandler(console_handler)
    return logger
logger = setup_logger(level=logging.INFO)
