# Copyright (C) 2019 The Electrum developers
# Distributed under the MIT software license, see the accompanying
# file LICENCE or http://www.opensource.org/licenses/mit-license.php
import logging
import logging.config


import os, platform, yaml, sys, subprocess, shlex
from typing import Optional


def setup_logging():
    with open("logging_config.yaml", "r") as f:
        config = yaml.safe_load(f.read())
        logging.config.dictConfig(config)

    global logger
    logger = logging.getLogger(__name__)

    # Set the function to handle uncaught exceptions
    def handle_uncaught_exception(exc_type, exc_value, exc_traceback):
        logger.critical(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = handle_uncaught_exception

    logger.info(
        f"========================= Starting Bitcoin Safe ========================"
    )
    logger.info(f"Version: {get_git_version()}")
    logger.info(f"Python version: {sys.version}. On platform: {describe_os_version()}")
    # logger.info(f"Logging to file: {str(logger.handlers[-1].filename)}")
    logger.info(f"Log filters: verbosity {logger.level}")


def describe_os_version() -> str:
    if "ANDROID_DATA" in os.environ:
        # from kivy import utils
        # if utils.platform != "android":
        #    return utils.platform
        import jnius

        bv = jnius.autoclass("android.os.Build$VERSION")
        b = jnius.autoclass("android.os.Build")
        return "Android {} on {} {} ({})".format(
            bv.RELEASE, b.BRAND, b.DEVICE, b.DISPLAY
        )
    else:
        return platform.platform()


def get_git_version() -> Optional[str]:
    dir = os.path.dirname(os.path.realpath(__file__))
    try:
        version = subprocess.check_output(
            shlex.split("git describe --exact-match --tags HEAD"), cwd=dir
        )
    except Exception:
        version = subprocess.check_output(shlex.split("git rev-parse HEAD"), cwd=dir)
    version = str(version, "utf8").strip()
    return version
