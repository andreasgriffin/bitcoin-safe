SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c

THIS_MAKEFILE := $(firstword $(MAKEFILE_LIST))
FLATHUB_ASSET_DIR := tools/build_linux/flathub_flatpak
BUILD_CACHE_ROOT := $(CURDIR)/.cache
TOOL_VENV_ROOT := $(CURDIR)/.tool-venv
APP_PYTHON := python3
PIP_CACHE_DIR := $(BUILD_CACHE_ROOT)/pip
POETRY_CACHE_DIR := $(BUILD_CACHE_ROOT)/poetry
POETRY_WHEEL_DIR := $(BUILD_CACHE_ROOT)/poetry-wheel
VENDOR_ROOT := /app/share/bitcoin-safe/vendor
BUILD_BACKENDS_DIR := $(VENDOR_ROOT)/build-backends

.PHONY: flatpak-app verify-runtime-imports

flatpak-app:
	command -v "$(APP_PYTHON)" >/dev/null
	export PYTHONDONTWRITEBYTECODE=1
	"$(APP_PYTHON)" -m venv "$(TOOL_VENV_ROOT)"
	"$(TOOL_VENV_ROOT)/bin/python" -m ensurepip --upgrade

	# Build frontend and backend tooling only need to exist in the temporary
	# tool venv; runtime packages are installed directly into /app below.
	"$(TOOL_VENV_ROOT)/bin/python" -m pip install \
		--no-build-isolation \
		--no-dependencies \
		--no-index \
		--find-links "$(BUILD_BACKENDS_DIR)" \
		--no-warn-script-location \
		--cache-dir "$(PIP_CACHE_DIR)" \
		-r "$(BUILD_BACKENDS_DIR)/requirements-build-backends.txt"

	rm -rf "$(POETRY_WHEEL_DIR)"
	mkdir -p "$(POETRY_WHEEL_DIR)"
	export POETRY_CACHE_DIR="$(POETRY_CACHE_DIR)"
	export PIP_CONFIG_FILE=/dev/null
	export PIP_DISABLE_PIP_VERSION_CHECK=1

	"$(TOOL_VENV_ROOT)/bin/poetry" build -f wheel --output "$(POETRY_WHEEL_DIR)"
	"$(APP_PYTHON)" -m pip install \
		--ignore-installed \
		--no-dependencies \
		--no-warn-script-location \
		--no-compile \
		--prefix=/app \
		--cache-dir "$(PIP_CACHE_DIR)" \
		"$(POETRY_WHEEL_DIR)"/*.whl

	$(MAKE) -f "$(THIS_MAKEFILE)" verify-runtime-imports

	install -Dm755 "$(FLATHUB_ASSET_DIR)/run-bitcoin-safe.sh" /app/bin/run-bitcoin-safe.sh
	install -Dm644 "$(FLATHUB_ASSET_DIR)/org.bitcoin_safe.BitcoinSafe.svg" /app/share/icons/hicolor/scalable/apps/org.bitcoin_safe.BitcoinSafe.svg
	install -Dm644 tools/resources/icon-128.png /app/share/icons/hicolor/128x128/apps/org.bitcoin_safe.BitcoinSafe.png
	install -Dm644 "$(FLATHUB_ASSET_DIR)/org.bitcoin_safe.BitcoinSafe.metainfo.xml" /app/share/metainfo/org.bitcoin_safe.BitcoinSafe.metainfo.xml
	install -Dm644 "$(FLATHUB_ASSET_DIR)/org.bitcoin_safe.BitcoinSafe.desktop" /app/share/applications/org.bitcoin_safe.BitcoinSafe.desktop
	mkdir -p /app/app
	ln -sfn ../share /app/app/share

	mkdir -p /app/lib/plugins
	for runtime_plugin_dir in /usr/lib/plugins/*; do
		plugin_dir_name="$$(basename "$${runtime_plugin_dir}")"
		if [ ! -e "/app/lib/plugins/$${plugin_dir_name}" ]; then
			ln -s "$${runtime_plugin_dir}" "/app/lib/plugins/$${plugin_dir_name}"
		fi
	done

	$(MAKE) -f "$(THIS_MAKEFILE)" verify-runtime-imports

	rm -rf "$(TOOL_VENV_ROOT)" "$(BUILD_CACHE_ROOT)" dist

verify-runtime-imports:
	"$(APP_PYTHON)" -c 'import appdirs'
	"$(APP_PYTHON)" -c 'import bitcoin_safe'
