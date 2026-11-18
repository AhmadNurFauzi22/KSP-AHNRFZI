import logging
import sys
from app.core.config import settings

def setup_logging():
    """Configure structured console & file logging."""
    log_format = "%(asctime)s - [%(levelname)s] - %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    level = logging.DEBUG if settings.APP_DEBUG else logging.INFO
    
    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger = logging.getLogger("ksp_ahnrfzi")
    logger.setLevel(level)
    return logger

logger = setup_logging()
