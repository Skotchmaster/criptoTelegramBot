import logging
import sys

def setup_logging(level=logging.INFO):
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    handlers = [logging.StreamHandler(sys.stdout)]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)
