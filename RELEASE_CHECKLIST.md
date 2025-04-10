* Update all translations
* Check is dependencies can be published on pypi if possible (not possible for git commit hash dependencies)
* Build for all platforms
* Test for all platforms
* Check the log, that zbar was loaded successfully (otherwise opencv is used)
* Sign all binaries
* `python tools/release.py`
* Create release notes for github, nostr, X