import logging

from server.logging_safety import AccessQueryFilter, configure_safe_logs


def test_access_log_discards_oauth_codes_and_other_query_values():
    record = logging.LogRecord('uvicorn.access', logging.INFO, '', 0,
        '%s - "%s %s HTTP/%s" %d', ('127.0.0.1', 'GET', '/auth/callback?code=fixture-private-code&state=fixture-private-state', '1.1', 200), None)
    assert AccessQueryFilter().filter(record)
    text = record.getMessage()
    assert '/auth/callback' in text and 'fixture-private' not in text and '?code=' not in text


def test_safe_logging_configuration_is_idempotent_and_quiets_provider_urls():
    configure_safe_logs(); configure_safe_logs()
    assert len([item for item in logging.getLogger('uvicorn.access').filters if isinstance(item, AccessQueryFilter)]) == 1
    assert logging.getLogger('httpx').level >= logging.WARNING
