import functools
import logging

_logger = logging.getLogger("VIPMUSIC.utils.errors")


def capture_internal_err(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            _logger.error(
                "Internal error in %s: %s", func.__name__, e, exc_info=True
            )
            return None

    return wrapper
