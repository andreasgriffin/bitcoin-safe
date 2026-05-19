# Contributing to Bitcoin-Safe

Thank you for your interest in contributing to Bitcoin-Safe! This project aims to be a secure, user-friendly Bitcoin wallet, and community contributions are essential to making that a reality. Please take a moment to read these guidelines before submitting your first contribution.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How to Contribute](#how-to-contribute)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Features](#suggesting-features)
  - [Security Vulnerabilities](#security-vulnerabilities)
  - [Submitting Code](#submitting-code)
- [Development Setup](#development-setup)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Project Structure](#project-structure)
- [Community & Communication](#community--communication)

---

## Code of Conduct

Bitcoin-Safe is committed to providing a welcoming and harassment-free environment for all contributors. By participating in this project, you agree to treat others with respect and professionalism. Disrespectful, abusive, or discriminatory behavior will not be tolerated and may result in removal from the project.

---

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/bitcoin-safe.git
   cd bitcoin-safe
   ```
3. **Add the upstream remote** to stay in sync:
   ```bash
   git remote add upstream https://github.com/andreasgriffin/bitcoin-safe.git
   ```
4. **Create a branch** for your work (see [Submitting Code](#submitting-code) for naming conventions).

---

## How to Contribute

### Reporting Bugs

Before opening a bug report, please search existing [issues](https://github.com/andreasgriffin/bitcoin-safe/issues) to avoid duplicates.

When filing a bug, include:

- **Bitcoin-Safe version** (shown in the Help → About dialog)
- **Operating system and version**
- **Python version** (`python --version`)
- **Steps to reproduce** the issue as precisely as possible
- **Expected vs. actual behavior**
- **Relevant logs or screenshots** (redact any private key material or seed phrases before posting)

> ⚠️ **Never include private keys, seed phrases, or wallet descriptors in bug reports.**

### Suggesting Features

Feature requests are welcome! Open an issue with the label `enhancement` and describe:

- The **problem** you are trying to solve
- Your **proposed solution** or behavior
- Any **alternatives** you have considered
- Whether this relates to a **specific Bitcoin use case** (e.g., multisig, hardware wallets, coin control)

### Security Vulnerabilities

**Do not open a public GitHub issue for security vulnerabilities.**

If you discover a security vulnerability, please report it responsibly via the [GitHub Security Advisory](https://github.com/andreasgriffin/bitcoin-safe/security/advisories/new) page, or by emailing the maintainers directly. Please allow reasonable time for a fix before any public disclosure.

This is especially important for issues that could affect:
- Private key or seed phrase exposure
- Transaction signing integrity
- Address generation correctness
- Network privacy (e.g., inadvertent broadcasting of sensitive data)

### Submitting Code

Contributions that fix bugs, add features, improve tests, or enhance documentation are all welcome.

For **non-trivial changes**, please open an issue first to discuss your approach. This avoids wasted effort if the change is out of scope or needs a different design.

---

## Development Setup

### Prerequisites

- Python 3.10 or higher
- `pip` and `virtualenv` (or equivalent)
- Git

### Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # On Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Run the application

```bash
python -m bitcoin_safe
```

### Running in Testnet / Regtest

For development and testing, avoid mainnet. Configure the network in the app settings or via environment variables as documented in the project README.

---

## Coding Standards

Bitcoin-Safe is written in Python. Please follow these conventions:

- **Style:** Adhere to [PEP 8](https://peps.python.org/pep-0008/). Code is linted with `flake8` and formatted with `black`.
- **Type hints:** Add type annotations to all new functions and methods.
- **Docstrings:** Document public functions and classes with clear, concise docstrings.
- **No magic constants:** Use named constants or configuration values for things like network parameters or fee rates.
- **Bitcoin correctness first:** Prioritize correctness and security over brevity. When in doubt, be explicit.

Run formatting and linting checks before pushing:

```bash
black .
flake8 .
mypy bitcoin_safe/
```

---

## Testing

All code changes should be accompanied by appropriate tests.

- **Unit tests** live in the `tests/` directory and are written with `pytest`.
- **Hardware wallet and network tests** may require special setup — see `tests/README.md` for details.
- Tests must not use mainnet keys or broadcast real transactions.

Run the test suite:

```bash
pytest
```

For coverage reporting:

```bash
pytest --cov=bitcoin_safe --cov-report=term-missing
```

New features should have tests that cover both the happy path and relevant edge cases (e.g., invalid inputs, network failures, signing edge cases).

---

## Pull Request Process

1. **Keep PRs focused.** One feature or bug fix per PR makes review faster.
2. **Rebase onto `main`** (or the active development branch) before opening your PR:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```
3. **Fill out the PR template** completely, including a description of the change and how to test it.
4. **Ensure all checks pass** — CI must be green before a PR can be merged.
5. **Be responsive to review feedback.** PRs that go stale without response may be closed.
6. **Do not force-push** to a branch after a review has started unless asked to.

PRs are merged by maintainers via squash or rebase merge to keep history clean.

---

## Commit Message Guidelines

Use clear, imperative commit messages in the following format:

```
<type>: <short summary> (50 chars or less)

<optional longer description explaining WHY, not just WHAT>
```

**Types:**

| Type       | When to use                                      |
|------------|--------------------------------------------------|
| `feat`     | A new feature                                    |
| `fix`      | A bug fix                                        |
| `security` | A security-related fix                           |
| `test`     | Adding or updating tests                         |
| `docs`     | Documentation only changes                      |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `chore`    | Build process, dependency updates, tooling       |
| `design`   | UI or UX changes                                 |

**Examples:**

```
feat: add PSBT import from clipboard
fix: correct fee estimation for segwit inputs
security: prevent seed phrase logging in debug output
docs: update hardware wallet setup guide
```

---

## Project Structure

```
bitcoin-safe/
├── bitcoin_safe/          # Main application package
│   ├── gui/               # PyQt-based user interface
│   ├── wallet/            # Wallet logic, descriptors, UTXO management
│   ├── signing/           # PSBT creation and signing flows
│   └── network/           # Node communication, broadcast
├── tests/                 # Pytest test suite
├── docs/                  # Documentation and screenshots
├── requirements.txt       # Runtime dependencies
├── requirements-dev.txt   # Development and test dependencies
└── README.md
```

---

## Community & Communication

- **[Subst Discussions](http://substr.network/s/bitcoin-safe)** — longer-form questions and ideas 
- **[GitHub Issues](https://github.com/andreasgriffin/bitcoin-safe/issues/new)** — bug reports, feature requests, and general discussion
- **`Pull Requests`** — code review and technical discussion

When asking questions, please include as much context as possible. Remember that maintainers and contributors are volunteers.

---

Thank you for helping make Bitcoin self-custody safer and more accessible for everyone. 🙏
