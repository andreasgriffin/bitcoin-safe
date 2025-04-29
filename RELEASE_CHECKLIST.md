## Before version tagging

* `poetry lock --no-cache` to ensure a complete lock file
* Update all translations
* Check if dependencies can be published on pypi if possible (not possible for git commit hash dependencies)

## Version tag

* ensure new version is in __init__ on main branch
* tag the main commit with the version

## After version tagging

* Build for all platforms
* Test for all platforms
* Check the log, that zbar was loaded successfully (in Mac this is tested automatically)
* Sign all binaries
* `python tools/release.py`
* Create release notes for github, nostr, X
* Publish release on github
* Update website with newest release
* Update features in https://github.com/thebitcoinhole/software-wallets
