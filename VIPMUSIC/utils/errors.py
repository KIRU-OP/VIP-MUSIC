import functools
import logging

_logger = logging.getLogger("VIPMUSIC.utils.errors")


def capture_internal_err(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            _logger.error(f"Internal error in {func.__name__}: {e}", exc_info=True)
            return None

    return wrapper
