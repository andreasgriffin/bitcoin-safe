import logging
import subprocess
import sys
import urllib.parse
import webbrowser
from typing import List

logger = logging.getLogger(__name__)


def compose_email(
    email: str, subject: str, body: str, attachment_filenames: List[str] = None, run_in_background=True
):
    # Encode the subject and body to ensure spaces and special characters are handled correctly
    subject_encoded = urllib.parse.quote(subject)
    body_encoded = urllib.parse.quote(body)
    mailto_link = f"mailto:{email}?subject={subject_encoded}&body={body_encoded}"

    # Function to attempt opening the mailto link with the OS's default email client
    def try_native_open(mailto_link):
        if sys.platform.startswith("linux"):
            # Linux: Use xdg-open to handle the mailto link
            subprocess.run(["xdg-open", mailto_link], check=True)
        elif sys.platform.startswith("darwin"):
            # macOS: Use open command to handle the mailto link
            subprocess.run(["open", mailto_link], check=True)
        elif sys.platform.startswith("win32"):
            # Windows: Use start command to handle the mailto link
            subprocess.run(["cmd", "/c", "start", "", mailto_link], check=True, shell=True)

    try:
        # Attempt to use the native OS command to open the email client
        try_native_open(mailto_link)
    except Exception as e:
        logger.debug(f"Failed to open the default email client using the OS native command: {e}")
        logger.debug("Attempting to open using webbrowser module...")
        # If the native OS command fails, fall back to using the webbrowser module
        webbrowser.open(mailto_link, new=0, autoraise=True)


if __name__ == "__main__":
    # Example usage
    compose_email(
        email="recipient@example.com", subject="Test Subject", body="This is a test body with spaces."
    )
