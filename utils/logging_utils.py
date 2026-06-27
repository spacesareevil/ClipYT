import sys
import logging

def setup_logging():
    # Set the root logger to INFO to prevent third-party noise
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    # Create a verbose formatter for our specific loggers
    verbose_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d - %(funcName)s): %(message)s'
    )

    # Create a console handler with the verbose formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(verbose_formatter)

    # Apply to specific modules
    for module in ['ui', 'services', 'utils']:
        logger = logging.getLogger(module)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(console_handler)
        logger.propagate = False