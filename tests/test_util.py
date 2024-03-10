import logging

logger = logging.getLogger(__name__)

from pathlib import Path
from unittest.mock import patch

from _pytest.logging import LogCaptureFixture
from PyQt6.QtCore import QObject, pyqtSignal

from bitcoin_safe.gui.qt.util import chained_one_time_signal_connections
from bitcoin_safe.util import path_to_rel_home_path, rel_home_path_to_abs_path


class TestClass(QObject):
    signal = pyqtSignal()


@patch("pathlib.Path.home")
def test_path_to_rel_home_path(mock_home):
    # Mock the home directory to a fixed path
    mock_home.return_value = Path("/home/user")

    # Define a test case
    test_abs_path = "/home/user/documents/test.txt"
    expected_rel_path = "documents/test.txt"

    # Test the path_to_rel_home_path function
    assert (
        path_to_rel_home_path(test_abs_path) == expected_rel_path
    ), "Failed to convert absolute path to relative path correctly"


@patch("pathlib.Path.home")
def test_rel_path_to_abs_path(mock_home):
    # Mock the home directory to a fixed path
    mock_home.return_value = Path("/home/user")

    # Define a test case
    test_rel_path = "documents/test.txt"
    expected_abs_path = "/home/user/documents/test.txt"

    # Test the rel_path_to_abs_path function
    assert (
        rel_home_path_to_abs_path(test_rel_path) == expected_abs_path
    ), "Failed to convert relative path to absolute path correctly"


@patch("pathlib.Path.home")
def test_rel_path_to_abs_path_with_given_absolute(mock_home):
    # Mock the home directory to a fixed path
    mock_home.return_value = Path("/home/user")

    # Define a test case
    test_rel_path = "/home/user/documents/test.txt"
    expected_abs_path = "/home/user/documents/test.txt"

    # Test the rel_path_to_abs_path function
    assert (
        rel_home_path_to_abs_path(test_rel_path) == expected_abs_path
    ), "Failed to convert relative path to absolute path correctly"


@patch("pathlib.Path.home")
def test_conversion_round_trip(mock_home):
    # Mock the home directory to a fixed path
    mock_home.return_value = Path("/home/user")

    # A path for round-trip conversion
    original_path = "/home/user/documents/round_trip_test.txt"

    # Convert to relative and back to absolute
    rel_path = path_to_rel_home_path(original_path)
    round_trip_path = rel_home_path_to_abs_path(rel_path)

    assert round_trip_path == original_path, "Round-trip conversion did not return the original path"


def test_chained_one_time_signal_connections(caplog: LogCaptureFixture):
    with caplog.at_level(logging.INFO):

        n = 4
        instances = [TestClass() for _ in range(n)]

        def factory(i, instance):
            def f(i=i, instance=instance):
                logger.info(str(i))
                return True

            return f

        fs = [factory(i, instance) for i, instance in enumerate(instances)]

        chained_one_time_signal_connections([instance.signal for instance in instances], fs)

        for instance in instances:
            instance.signal.emit()
            instance.signal.emit()

        for instance in instances:
            instance.signal.emit()
            instance.signal.emit()

        assert [record.msg for record in caplog.records] == [str(i) for i in range(n)]


def test_chained_one_time_signal_connections_prevent_disconnect(caplog: LogCaptureFixture):
    # repeat, but now do not return True
    with caplog.at_level(logging.INFO):

        n = 4
        instances = [TestClass() for _ in range(n)]

        def factory(i, instance):
            def f(i=i, instance=instance):
                logger.info(str(i))
                return None

            return f

        fs = [factory(i, instance) for i, instance in enumerate(instances)]

        chained_one_time_signal_connections([instance.signal for instance in instances], fs)

        for instance in instances:
            instance.signal.emit()

        for instance in instances:
            instance.signal.emit()

        # since f(0) == None, the 1. signal simply reconnects
        assert [record.msg for record in caplog.records] == ["0", "0"]
