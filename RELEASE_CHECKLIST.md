## Before tagging

* `poetry update` to ensure an up-to-date lock file
* Update all translations

## Prepare 1

* tag the main commit with the version
* Build for all platforms
* Sign all binaries
* `python tools/release.py`  (as draft)
* Create release notes for github, nostr, substr, X

## Prepare Plugins

* `poetry update` in the plugins directory --> Update (if necessary) bitcoin safe compatibility strings.  Pytest and deploy.

## Publish

* Publish release on github
* `bash fetch_release.sh` in website repo
* Publish release notes


## Maybe
* Update features in https://github.com/thebitcoinhole/software-wallets  and check in https://github.com/bitcoin-dot-org/Bitcoin.org/
