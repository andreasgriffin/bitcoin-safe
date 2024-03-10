import logging
import sys
from unittest.mock import patch

from _pytest.logging import LogCaptureFixture

from bitcoin_safe.logging_setup import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def test_no_error_logging(caplog: LogCaptureFixture):
    with patch("bitcoin_safe.logging_handlers.compose_email") as mock_compose_email:
        mock_compose_email.return_value = "Mocked Function"

        with caplog.at_level(logging.INFO):
            try:
                int("aaa")
            except Exception as e:
                logger.error(str(e))

            # Check that no exc_info is included
            assert not caplog.records[-1].exc_info

            mock_compose_email.assert_not_called()


def test_exception_logging(caplog: LogCaptureFixture):
    with patch("bitcoin_safe.logging_handlers.compose_email") as mock_compose_email:
        mock_compose_email.return_value = "Mocked Function"

        with caplog.at_level(logging.INFO):
            logger.critical("this should compose an email", exc_info=sys.exc_info())

            # Assert that the mocked function was called
            mock_compose_email.assert_called_once()
