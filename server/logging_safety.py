"""Never retain OAuth codes, tokens or other URL query values in access logs."""
import logging


class AccessQueryFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn's access tuple is client, method, target, version, status.
        if isinstance(record.args, tuple) and len(record.args) == 5 and isinstance(record.args[2], str):
            values = list(record.args)
            values[2] = values[2].split('?', 1)[0]
            record.args = tuple(values)
        return True


def configure_safe_logs():
    logger = logging.getLogger('uvicorn.access')
    if not any(isinstance(item, AccessQueryFilter) for item in logger.filters):
        logger.addFilter(AccessQueryFilter())
    # Provider request URLs can also contain signed query credentials.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
