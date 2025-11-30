## Before version tagging

* `poetry lock --no-cache` to ensure a complete lock file
* Update all translations
* Check if dependencies can be published on pypi if possible (not possible for git commit hash dependencies)

## Version tag

* ensure new version is in __init__ on main branch
* tag the main commit with the version

## After version tagging

* Build for all platforms
* Check the screenshots in the workflow logs
* Test for all platforms
* Sign all binaries
* `python tools/release.py`  (as draft)
  * For the upgrade from 1.6.0 to next version: additionally upload the appimage on the release page
* Create release notes for github, nostr, X
* Publish release on github
* `bash fetch_release.sh` in website repo
* Update features in https://github.com/thebitcoinhole/software-wallets  and check in https://github.com/bitcoin-dot-org/Bitcoin.org/
