# Security Policy

Bitcoin Safe is security-sensitive software used to coordinate Bitcoin
cold-storage wallets and hardware signers. Thank you for reporting potential
security issues responsibly.

## Reporting a vulnerability

Please **do not open a public GitHub issue** for an unpatched vulnerability.
Instead, send a confidential report to **andreasgriffin@proton.me**.

Include the affected version/commit, impacted component, security impact,
attacker prerequisites and, if possible, minimal reproduction steps using
synthetic data or Bitcoin regtest. Do not send real wallet seeds, private keys,
real-money transactions, or private information belonging to others.

If a demo seed is needed to reproduce, then use one of the test seeds in tests/non_gui/test_signers.py

Please allow time for triage and remediation before public disclosure. We
cannot promise a specific response or patch timeline, but actionable reports
with a clear security impact are welcome.

## Supported versions

Security fixes are normally developed against the active codebase. Check the
project's release information for available updates. This document does not
promise backports for every older release.
