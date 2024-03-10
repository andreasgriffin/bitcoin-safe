import logging
import os
import platform
import sys

from .simple_mailer import compose_email


def remove_absolute_paths(line: str):
    """
    Replaces absolute paths in a traceback line with relative ones,
    based on the current script's execution path.
    """
    current_path = os.getcwd() + os.sep
    return line.replace(current_path, "")


def mail_error_repot(error_report: str):
    email = "andreasgriffin@proton.me"
    subject = "Error report"
    body = f"""Error:
            {error_report}
            """.replace(
        "    ", ""
    )

    # Write additional system info if needed
    body += "\n\nSystem Info:\n"
    body += f"OS: {platform.platform()}\n"
    body += f"Python Version: {sys.version}\n\n"
    return compose_email(email, subject, body)


class RelativePathFormatter(logging.Formatter):
    def formatException(self, exc_info):
        return remove_absolute_paths(super().formatException(exc_info))

    def format(self, record):
        if record.exc_info:
            record.exc_text = self.formatException(record.exc_info)
        return super().format(record)


class MailHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET, must_include_exc_info=True) -> None:
        super().__init__(level)
        self.must_include_exc_info = must_include_exc_info

    def emit(self, record):
        """'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename', 'funcName', 'getMessage', 'levelname', 'levelno', 'lineno', 'message', 'module', 'msecs', 'msg', 'name', 'pathname', 'process', 'processName', 'relativeCreated', 'stack_info', 'thread', 'threadName"""

        if (self.must_include_exc_info and record.exc_info) or not self.must_include_exc_info:
            exc_type, exc_value, exc_traceback = record.exc_info

            message = str(self.format(record))
            mail_error_repot(message)
