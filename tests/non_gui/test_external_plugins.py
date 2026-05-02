#
# Bitcoin Safe
# Copyright (C) 2026 Andreas Griffin
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of version 3 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see https://www.gnu.org/licenses/gpl-3.0.html
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Callable, Coroutine
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import Any

import bdkpython as bdk
import pytest
from bitcoin_safe_lib.async_tools.loop_in_thread import ExcInfo, MultipleStrategy
from bitcoin_safe_lib.gui.qt.spinning_button import SpinningButton
from bitcoin_safe_lib.storage import BaseSaveableClass
from btcpay_tools.btcpay_subscription_nostr.service import (
    SubscriptionManagementPhase,
    SubscriptionManagementStatus,
    SubscriptionManagementStatusCode,
)
from btcpay_tools.config import BTCPayConfig, PlanDuration
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from bitcoin_safe.config import UserConfig
from bitcoin_safe.gui.qt.language_chooser import LanguageChooser
from bitcoin_safe.gui.qt.settings import Settings
from bitcoin_safe.gui.qt.sidebar.sidebar_tree import SidebarNode, SidebarRow, SidebarTree
from bitcoin_safe.network_utils import ProxyInfo, fetch_bytes
from bitcoin_safe.plugin_framework.builtin_plugins import (
    BUILTIN_PLUGIN_BUNDLES_BY_CLIENT_CLASS,
)
from bitcoin_safe.plugin_framework.external_plugin_registry import (
    ExternalPluginRegistry,
)
from bitcoin_safe.plugin_framework.external_plugin_registry_dataclasses import (
    ExternalPluginCatalogEntry,
    ExternalPluginError,
    InstalledSourcePluginMetadata,
    PluginSource,
    PluginSourceAuthConfig,
    VerifiedPluginSourceManifest,
)
from bitcoin_safe.plugin_framework.external_plugin_resources import (
    ExternalPluginResources,
    load_external_plugin_btcpay_config,
    resolve_external_plugin_package_root,
)
from bitcoin_safe.plugin_framework.paid_plugin_client import PaidPluginClient
from bitcoin_safe.plugin_framework.plugin_bundle import (
    PluginRuntimeContext,
    RuntimePluginBundle,
    create_runtime_plugin_clients,
    ensure_plugin_import_path,
    normalize_runtime_plugin_bundle,
    normalize_static_plugin_bundle,
    register_static_plugin_bundle,
)
from bitcoin_safe.plugin_framework.plugin_client import PluginClient
from bitcoin_safe.plugin_framework.plugin_identity import PluginSource as PluginClientSource
from bitcoin_safe.plugin_framework.plugin_manager import (
    PluginManager,
    PluginManagerWidget,
    SourceCatalogItem,
)
from bitcoin_safe.plugin_framework.plugin_server import PluginPermission
from bitcoin_safe.plugin_framework.plugin_source_models import (
    PluginSourceModelError,
    parse_plugin_pyproject,
    parse_source_manifest,
)
from bitcoin_safe.plugin_framework.plugins.business_plan.client import BusinessPlanItem
from bitcoin_safe.plugin_framework.plugins.chat_sync.client import SyncClient
from bitcoin_safe.plugin_framework.plugins.walletgraph.client import WalletGraphClient
from bitcoin_safe.plugin_framework.subscription_manager import (
    StoredSubscriptionStatus,
    SubscriptionManager,
)
from bitcoin_safe.signals import Signals, WalletFunctions
from tests.btcpay_support import (
    TEST_BTCPAY_SUBSCRIPTION_CONFIG,
)


class _DummyFX:
    class _Signal:
        def connect(self, _slot) -> None:
            return None

    def __init__(self) -> None:
        self.signal_data_updated = self._Signal()

    def get_rate(self, _currency: str):
        return None

    def list_rates(self) -> dict[str, dict[str, str]]:
        return {}


class _ImmediateLoopInThread:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_task(self, coro: Coroutine[Any, Any, object], **kwargs: object) -> None:
        self.calls.append(kwargs)
        result: object = None
        error_info: tuple[type[BaseException], BaseException, TracebackType | None] | None = None

        def run() -> None:
            nonlocal result, error_info
            try:
                result = asyncio.run(coro)
            except Exception as exc:
                error_info = (type(exc), exc, exc.__traceback__)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join()

        if error_info is not None:
            on_error = kwargs.get("on_error")
            if callable(on_error):
                on_error(error_info)
            return

        on_success = kwargs.get("on_success")
        if callable(on_success):
            on_success(result)

        on_done = kwargs.get("on_done")
        if callable(on_done):
            on_done(result)


class _DisplayMetadataPluginClient(PluginClient):
    VERSION = "0.0.1"

    def __init__(self) -> None:
        super().__init__(enabled=True, icon=QIcon())

    def load(self) -> None:
        return None

    def unload(self) -> None:
        return None


class _TrackingPluginClient(_DisplayMetadataPluginClient):
    def __init__(self) -> None:
        super().__init__()
        self.reload_translator_calls = 0
        self.update_ui_calls = 0

    def reload_translator(self) -> None:
        self.reload_translator_calls += 1

    def updateUi(self) -> None:
        self.update_ui_calls += 1


class _LoadTrackingPluginClient(_DisplayMetadataPluginClient):
    def __init__(self, enabled: bool = True) -> None:
        super().__init__()
        self.load_calls = 0
        self.unload_calls = 0
        self.enabled = enabled
        self.node.setVisible(enabled)

    def load(self) -> None:
        self.load_calls += 1

    def unload(self) -> None:
        self.unload_calls += 1


def _stored_subscription_status(
    status: SubscriptionManagementStatus | None,
    checked_at_ts: float = 123.0,
) -> StoredSubscriptionStatus:
    return StoredSubscriptionStatus(
        status=status,
        checked_at_ts=checked_at_ts if status else None,
        last_status_error=None,
    )


class _PaidStateTrackingPluginClient(PaidPluginClient):
    VERSION = "0.1.0"
    title = "Test Paid Plugin"
    description = "Tracks paid-plugin state through runtime replacement."
    provider = "Tests"
    subscription_product_id = "demo-plugin"

    @classmethod
    def cls_kwargs(
        cls,
        config: UserConfig,
        fx: _DummyFX,
        loop_in_thread: _ImmediateLoopInThread | None,
        additional_access_providers: list[Callable[[], bool]] | None = None,
        parent: QWidget | None = None,
        subscription_managers: dict[str, SubscriptionManager] | None = None,
        selected_subscription_key: str | None = None,
    ) -> dict[str, object]:
        data = super().cls_kwargs(
            config=config,
            fx=fx,
            loop_in_thread=loop_in_thread,
            additional_access_providers=additional_access_providers,
            parent=parent,
        )
        if subscription_managers is not None:
            data["subscription_managers"] = subscription_managers
        if selected_subscription_key is not None:
            data["selected_subscription_key"] = selected_subscription_key
        return data

    def __init__(
        self,
        config: UserConfig,
        fx: _DummyFX,
        loop_in_thread: _ImmediateLoopInThread | None,
        additional_access_providers: list[Callable[[], bool]] | None,
        enabled: bool = False,
        subscription_managers: dict[str, SubscriptionManager] | None = None,
        selected_subscription_key: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            config=config,
            fx=fx,
            loop_in_thread=loop_in_thread,
            icon=QIcon(),
            btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
            enabled=enabled,
            additional_access_providers=additional_access_providers,
            subscription_managers=subscription_managers,
            selected_subscription_key=selected_subscription_key,
            parent=parent,
        )
        self.load_calls = 0
        self.unload_calls = 0

    def load_paid_plugin(self) -> None:
        self.load_calls += 1

    def unload_paid_plugin(self) -> None:
        self.unload_calls += 1


class _CloseTrackingPluginClient(_DisplayMetadataPluginClient):
    def __init__(self) -> None:
        super().__init__()
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        return super().close()


class _FailingFromDumpPluginClient(_DisplayMetadataPluginClient):
    should_fail = True

    @classmethod
    def from_dump(cls, dct: dict[str, object], class_kwargs: dict | None = None):
        if cls.should_fail:
            raise RuntimeError("boom")
        return super().from_dump(dct, class_kwargs=class_kwargs)


class _GenericBuiltinBundleModule:
    PLUGIN_CLIENTS = (_DisplayMetadataPluginClient,)

    @staticmethod
    def class_kwargs(_context: PluginRuntimeContext) -> dict[str, dict[str, object]]:
        return {_DisplayMetadataPluginClient.__name__: {}}


class _FactoryRuntimeBundleModule(_GenericBuiltinBundleModule):
    @staticmethod
    def create_plugin_clients(
        context: PluginRuntimeContext,
        descriptor: bdk.Descriptor,
    ) -> tuple[PluginClient, ...]:
        del context, descriptor
        return (_DisplayMetadataPluginClient(),)


class _FailingFactoryRuntimeBundleModule(_GenericBuiltinBundleModule):
    @staticmethod
    def create_plugin_clients(
        context: PluginRuntimeContext,
        descriptor: bdk.Descriptor,
    ) -> tuple[PluginClient, ...]:
        del context, descriptor
        raise RuntimeError("boom")


class _FailingBuiltinBundleModule:
    PLUGIN_CLIENTS = (_FailingFromDumpPluginClient,)

    @staticmethod
    def class_kwargs(_context: PluginRuntimeContext) -> dict[str, dict[str, object]]:
        return {_FailingFromDumpPluginClient.__name__: {}}


class _PartiallyFailingBuiltinBundleModule:
    PLUGIN_CLIENTS = (_FailingFromDumpPluginClient, _DisplayMetadataPluginClient)

    @staticmethod
    def class_kwargs(_context: PluginRuntimeContext) -> dict[str, dict[str, object]]:
        return {
            _FailingFromDumpPluginClient.__name__: {},
            _DisplayMetadataPluginClient.__name__: {},
        }


def _make_config(tmp_path: Path) -> UserConfig:
    config = UserConfig()
    config.config_dir = tmp_path / "config"
    config.network = bdk.Network.REGTEST
    return config


def _make_runtime_context(tmp_path: Path) -> PluginRuntimeContext:
    return PluginRuntimeContext(
        wallet_functions=WalletFunctions(Signals()),
        config=_make_config(tmp_path),
        fx=_DummyFX(),
        loop_in_thread=None,
        subscription_price_lookup=None,
        parent=None,
    )


def _installed_source_plugin_metadata(
    source_id: str,
    bundle_id: str,
    version: str = "1.0.0",
    folder_hash: str = "hash",
) -> InstalledSourcePluginMetadata:
    return InstalledSourcePluginMetadata(
        bundle_id=bundle_id,
        source_id=source_id,
        version=version,
        folder_hash=folder_hash,
        installed_at="2026-04-21T00:00:00+00:00",
        trusted_auto_allow_signer=False,
        verified_signer_fingerprint="fingerprint",
    )


def _test_descriptor() -> bdk.Descriptor:
    return bdk.Descriptor(
        "wpkh([44250c36/84'/1'/0']tpubDCrUjjHLB1fxk1oRveETjw62z8jsUuqx7JkBUW44VBszGmcY3Eun3apwVcE5X2bfF5MsM3uvuQDed6Do33ZN8GiWcnj2QPqVDspFT1AyZJ9/0/*)",
        bdk.Network.REGTEST,
    )


def _plugin_manager_init_kwargs(
    tmp_path: Path, loop_in_thread: _ImmediateLoopInThread | None = None
) -> dict[str, object]:
    config = _make_config(tmp_path)
    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    external_registry = ExternalPluginRegistry.from_config(config)
    return PluginManager.cls_kwargs(
        wallet_functions=wallet_functions,
        config=config,
        fx=_DummyFX(),
        loop_in_thread=loop_in_thread,
        external_registry=external_registry,
    )


def _plugin_manager_class_kwargs(
    tmp_path: Path, loop_in_thread: _ImmediateLoopInThread | None = None
) -> dict[str, dict[str, object]]:
    return {
        PluginManager.__name__: _plugin_manager_init_kwargs(tmp_path, loop_in_thread=loop_in_thread),
    }


def _mark_source_refresh_run(
    manager: PluginManager,
    refresh_calls: list[bool],
    show_errors: bool,
) -> None:
    refresh_calls.append(show_errors)
    manager.external_registry.last_download_time = datetime.now(timezone.utc)


def _serialized_client_payload(client: PluginClient) -> str:
    return BaseSaveableClass.dumps_object(client.dump())


def _patch_plugin_manager_for_builtin_client(
    monkeypatch,
    client_cls: type[PluginClient],
    module,
) -> None:
    runtime_bundle = normalize_runtime_plugin_bundle(
        module=module,
        context=_make_runtime_context(Path("/tmp")),
        auto_allow_plugin_clients=module.PLUGIN_CLIENTS,
    )
    base_known_classes = PluginManager._base_known_classes.copy()
    base_known_classes[client_cls.__name__] = client_cls
    base_client_classes = [*PluginManager._base_client_classes, client_cls]

    monkeypatch.setattr(PluginManager, "_base_known_classes", base_known_classes)
    monkeypatch.setattr(PluginManager, "known_classes", base_known_classes.copy())
    monkeypatch.setattr(PluginManager, "client_classes", base_client_classes.copy())
    monkeypatch.setattr(PluginManager, "_base_client_classes", base_client_classes)
    monkeypatch.setattr(
        PluginManager, "_static_runtime_bundles", staticmethod(lambda _context: (runtime_bundle,))
    )
    monkeypatch.setattr(
        PluginManager,
        "_refresh_external_state",
        classmethod(lambda cls, context, external_registry: {}),
    )


def _write_plugin_svg(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">',
                '  <path fill="currentColor" d="M8 1 2 4v4c0 3.3 2.2 6.3 6 7 3.8-.7 6-3.7 6-7V4L8 1Z"/>',
                "</svg>",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _plugin_pyproject_text(version: str = "1.0.0") -> str:
    return "\n".join(
        [
            "[tool.poetry]",
            'name = "test-plugin"',
            f'version = "{version}"',
            'description = "Test description"',
            "[tool.bitcoin_safe.plugin]",
            'bundle_id = "test-plugin"',
            'display_name = "Test Plugin"',
            'description = "Test description"',
            'provider = "Tests"',
            'schema_version = "1"',
            'plugin_api_version = "1"',
            'entrypoint = "test_plugin/plugin_bundle.py"',
            'bitcoin_safe_version = ">=0.0.0"',
            "",
        ]
    )


def _btcpay_config() -> BTCPayConfig:
    return BTCPayConfig.model_validate(
        {
            "btcpay_base": {
                "base_url": "https://testnet.demo.btcpayserver.org",
                "pos_app_id": "3sgZmTZfKP8mRQciCqNh6g5F1G1s",
                "store_id": "98rXQCLFR3jmjbh5V5BomnqKJT5xC9kYejFRJHfmLWBq",
            },
            "client": {
                "npub_bitcoin_safe_pos": ("npub150ncc39ala3h9zudddrjqy9f7wenp7d20rjm99wchwtkdpze07wqukr9cu")
            },
            "products": {
                "demo-plugin": [
                    {
                        "offering_id": "offering_89j5mBhvUYuvFfxNL1",
                        "plan_id": "plan_Bqm6FpomH4TvZLj113",
                        "pos_id": "demo-plugin",
                        "trial_pos_id": "demo-plugin-trial",
                        "duration": "month",
                    }
                ]
            },
        }
    )


def _write_minimal_plugin_manifest(package_root: Path) -> None:
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / "plugin.yaml").write_text(
        "\n".join(
            [
                'schema_version: "1"',
                'bundle_id: "test-plugin"',
                'version: "0.1.0"',
                'display_name: "Test Plugin"',
                'description: "Test plugin"',
                "authors:",
                '  - "Tests <tests@example.com>"',
                'provider: "Tests"',
                'plugin_api_version: "1"',
                'entrypoint: "test_plugin/plugin_bundle.py"',
                'bitcoin_safe_version: ">=0.0.0,<999.0.0"',
                'python: ">=3.10,<3.13"',
                "btcpay:",
                "  btcpay_base:",
                '    base_url: "https://testnet.demo.btcpayserver.org"',
                '    pos_app_id: "3sgZmTZfKP8mRQciCqNh6g5F1G1s"',
                '    store_id: "98rXQCLFR3jmjbh5V5BomnqKJT5xC9kYejFRJHfmLWBq"',
                "  client:",
                '    npub_bitcoin_safe_pos: "npub150ncc39ala3h9zudddrjqy9f7wenp7d20rjm99wchwtkdpze07wqukr9cu"',
                "  products:",
                "    demo-plugin:",
                '      - offering_id: "offering_89j5mBhvUYuvFfxNL1"',
                '        plan_id: "plan_Bqm6FpomH4TvZLj113"',
                '        pos_id: "demo-plugin"',
                '        trial_pos_id: "demo-plugin-trial"',
                '        duration: "month"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_register_static_plugin_bundle_defaults_auto_allow_to_plugin_clients() -> None:
    registration = register_static_plugin_bundle(_GenericBuiltinBundleModule)

    assert registration.module.PLUGIN_CLIENTS == _GenericBuiltinBundleModule.PLUGIN_CLIENTS
    assert registration.auto_allow_plugin_clients == _GenericBuiltinBundleModule.PLUGIN_CLIENTS


def test_ensure_plugin_import_path_prepends_once(tmp_path: Path) -> None:
    other_path = str(tmp_path / "other")
    target_path = tmp_path / "plugins"
    target_path.mkdir()
    original_sys_path = sys.path[:]
    sys.path[:] = [other_path]
    try:
        ensure_plugin_import_path(target_path)
        ensure_plugin_import_path(target_path)

        assert sys.path[0] == str(target_path.resolve())
        assert sys.path.count(str(target_path.resolve())) == 1
        assert sys.path[1:] == [other_path]
    finally:
        sys.path[:] = original_sys_path


def test_create_runtime_plugin_clients_uses_generic_from_dump(qapp: QApplication, tmp_path: Path) -> None:
    del qapp
    registration = register_static_plugin_bundle(_GenericBuiltinBundleModule)
    context = _make_runtime_context(tmp_path)
    runtime_bundle = normalize_static_plugin_bundle(bundle=registration, context=context)

    clients = create_runtime_plugin_clients(
        bundle=runtime_bundle,
        context=context,
        descriptor=bdk.Descriptor(
            "wpkh([44250c36/84'/1'/0']tpubDCrUjjHLB1fxk1oRveETjw62z8jsUuqx7JkBUW44VBszGmcY3Eun3apwVcE5X2bfF5MsM3uvuQDed6Do33ZN8GiWcnj2QPqVDspFT1AyZJ9/0/*)",
            bdk.Network.REGTEST,
        ),
    )

    assert len(clients) == 1
    assert isinstance(clients[0], _DisplayMetadataPluginClient)


def test_builtin_plugin_registry_uses_bundle_modules_for_current_builtins() -> None:
    assert BUILTIN_PLUGIN_BUNDLES_BY_CLIENT_CLASS[SyncClient].module.PLUGIN_CLIENTS == (SyncClient,)
    assert BUILTIN_PLUGIN_BUNDLES_BY_CLIENT_CLASS[WalletGraphClient].module.PLUGIN_CLIENTS == (
        WalletGraphClient,
    )
    assert BusinessPlanItem not in BUILTIN_PLUGIN_BUNDLES_BY_CLIENT_CLASS


def test_source_manifest_rejects_path_traversal_identifiers() -> None:
    with pytest.raises(PluginSourceModelError):
        parse_source_manifest(
            {
                "schema_version": "1",
                "source_id": "../source",
                "display_name": "Test Source",
                "source_serial": 1,
                "plugins": [],
            },
            "source.toml",
        )

    with pytest.raises(PluginSourceModelError):
        parse_source_manifest(
            {
                "schema_version": "1",
                "source_id": "test-source",
                "display_name": "Test Source",
                "source_serial": 1,
                "plugins": [
                    {
                        "bundle_id": "../plugin",
                        "folder_hash": "hash",
                        "release_ref": "main",
                    }
                ],
            },
            "source.toml",
        )

    with pytest.raises(PluginSourceModelError):
        parse_source_manifest(
            {
                "schema_version": "1",
                "source_id": "test-source",
                "display_name": "Test Source",
                "source_serial": 1,
                "plugins": [
                    {
                        "bundle_id": "test-plugin",
                        "folder_hash": "hash",
                        "release_ref": "../main",
                    }
                ],
            },
            "source.toml",
        )


def test_plugin_pyproject_rejects_unsafe_entrypoint() -> None:
    with pytest.raises(PluginSourceModelError):
        parse_plugin_pyproject(
            {
                "tool": {
                    "poetry": {
                        "name": "test-plugin",
                        "version": "1.0.0",
                        "description": "Test plugin",
                    },
                    "bitcoin_safe": {
                        "plugin": {
                            "schema_version": "1",
                            "display_name": "Test Plugin",
                            "plugin_api_version": "1",
                            "entrypoint": "../plugin_bundle.py",
                            "bitcoin_safe_version": ">=0.0.0",
                        }
                    },
                }
            },
            "pyproject.toml",
        )


def test_normalize_runtime_plugin_bundle_keeps_optional_factory(tmp_path: Path) -> None:
    runtime_bundle = normalize_runtime_plugin_bundle(
        module=_FactoryRuntimeBundleModule,
        context=_make_runtime_context(tmp_path),
        auto_allow_plugin_clients=_FactoryRuntimeBundleModule.PLUGIN_CLIENTS,
    )

    assert isinstance(runtime_bundle, RuntimePluginBundle)
    assert runtime_bundle.create_plugin_clients is not None


def test_create_runtime_plugin_clients_accepts_factory_hook(qapp: QApplication, tmp_path: Path) -> None:
    del qapp
    runtime_bundle = normalize_runtime_plugin_bundle(
        module=_FactoryRuntimeBundleModule,
        context=_make_runtime_context(tmp_path),
        auto_allow_plugin_clients=_FactoryRuntimeBundleModule.PLUGIN_CLIENTS,
    )

    clients = create_runtime_plugin_clients(
        bundle=runtime_bundle,
        context=_make_runtime_context(tmp_path),
        descriptor=bdk.Descriptor(
            "wpkh([44250c36/84'/1'/0']tpubDCrUjjHLB1fxk1oRveETjw62z8jsUuqx7JkBUW44VBszGmcY3Eun3apwVcE5X2bfF5MsM3uvuQDed6Do33ZN8GiWcnj2QPqVDspFT1AyZJ9/0/*)",
            bdk.Network.REGTEST,
        ),
    )

    assert len(clients) == 1
    assert isinstance(clients[0], _DisplayMetadataPluginClient)


def test_create_runtime_plugin_clients_skips_failed_factory_hook(qapp: QApplication, tmp_path: Path) -> None:
    del qapp
    runtime_bundle = normalize_runtime_plugin_bundle(
        module=_FailingFactoryRuntimeBundleModule,
        context=_make_runtime_context(tmp_path),
        auto_allow_plugin_clients=_FailingFactoryRuntimeBundleModule.PLUGIN_CLIENTS,
    )

    clients = create_runtime_plugin_clients(
        bundle=runtime_bundle,
        context=_make_runtime_context(tmp_path),
        descriptor=_test_descriptor(),
    )

    assert clients == ()


def test_create_runtime_plugin_clients_skips_failed_client_from_dump(
    qapp: QApplication, tmp_path: Path
) -> None:
    del qapp
    _FailingFromDumpPluginClient.should_fail = True
    runtime_bundle = normalize_runtime_plugin_bundle(
        module=_PartiallyFailingBuiltinBundleModule,
        context=_make_runtime_context(tmp_path),
        auto_allow_plugin_clients=_PartiallyFailingBuiltinBundleModule.PLUGIN_CLIENTS,
    )

    try:
        clients = create_runtime_plugin_clients(
            bundle=runtime_bundle,
            context=_make_runtime_context(tmp_path),
            descriptor=_test_descriptor(),
        )
    finally:
        _FailingFromDumpPluginClient.should_fail = True

    assert len(clients) == 1
    assert isinstance(clients[0], _DisplayMetadataPluginClient)


def test_external_registry_derives_archive_url_from_manifest_url() -> None:
    manifest_url = "https://dummyurl.org/andreasgriffin/bitcoin-safe-plugins/raw/branch/main/source.toml"

    archive_url = ExternalPluginRegistry._archive_url_from_manifest_url(manifest_url, "main")

    assert archive_url == "https://dummyurl.org/andreasgriffin/bitcoin-safe-plugins/archive/main.zip"


def test_external_registry_derives_archive_url_from_raw_github_manifest_url() -> None:
    manifest_url = "https://raw.githubusercontent.com/andreasgriffin/bitcoin-safe-plugins/main/source.toml"

    archive_url = ExternalPluginRegistry._archive_url_from_manifest_url(manifest_url, "main")

    assert archive_url == "https://github.com/andreasgriffin/bitcoin-safe-plugins/archive/main.zip"


def test_external_registry_normalizes_repo_url_to_manifest_url() -> None:
    manifest_url = ExternalPluginRegistry._normalize_manifest_url(
        "https://dummyurl.org/andreasgriffin/bitcoin-safe-plugins"
    )

    assert (
        manifest_url == "https://dummyurl.org/andreasgriffin/bitcoin-safe-plugins/raw/branch/main/source.toml"
    )


def test_external_registry_normalizes_git_repo_url_to_manifest_url() -> None:
    manifest_url = ExternalPluginRegistry._normalize_manifest_url(
        "https://dummyurl.org/andreasgriffin/bitcoin-safe-plugins.git"
    )

    assert (
        manifest_url == "https://dummyurl.org/andreasgriffin/bitcoin-safe-plugins/raw/branch/main/source.toml"
    )


def test_external_registry_install_plugin_restores_previous_files_on_swap_failure(
    tmp_path: Path, monkeypatch
) -> None:
    config = _make_config(tmp_path)
    registry = ExternalPluginRegistry(
        PluginRuntimeContext(
            wallet_functions=WalletFunctions(Signals()),
            config=config,
            fx=_DummyFX(),
            loop_in_thread=None,
            subscription_price_lookup=None,
            parent=None,
        )
    )
    source = PluginSource(
        source_id="test-source",
        display_name="Test Source",
        manifest_url="https://dummy.example/source.toml",
        pinned_source_public_key="key",
        auth_config=PluginSourceAuthConfig(),
    )
    plugin = ExternalPluginCatalogEntry(
        source_id="test-source",
        source_display_name="Test Source",
        bundle_id="test-plugin",
        version="2.0.0",
        display_name="Test Plugin",
        description="Test description",
        provider="Tests",
        entrypoint="test_plugin/plugin_bundle.py",
        plugin_api_version="1",
        app_version_specifier=">=0.0.0",
        folder_hash="new-hash",
        release_ref="main",
    )
    manifest = VerifiedPluginSourceManifest(
        source_id="test-source",
        display_name="Test Source",
        source_serial=1,
        signer_fingerprint="fingerprint",
        manifest_url=source.manifest_url,
        plugins=(plugin,),
    )
    existing_install = registry.installed_dir / plugin.bundle_id
    existing_install.mkdir(parents=True)
    (existing_install / "version.txt").write_text("old", encoding="utf-8")

    prepared_plugin_dir = tmp_path / "prepared-plugin"
    prepared_plugin_dir.mkdir()
    (prepared_plugin_dir / "pyproject.toml").write_text("[tool.poetry]\nname='test'\n", encoding="utf-8")
    (prepared_plugin_dir / "version.txt").write_text("new", encoding="utf-8")

    monkeypatch.setattr(
        registry, "load_source", lambda source_id: source if source_id == source.source_id else None
    )
    monkeypatch.setattr(
        registry,
        "load_cached_source_catalog",
        lambda source_id: manifest if source_id == source.source_id else None,
    )
    monkeypatch.setattr(registry, "_prepare_plugin_directory", lambda *_args: prepared_plugin_dir)
    monkeypatch.setattr(
        registry,
        "_load_plugin_metadata",
        lambda _metadata_path: SimpleNamespace(bundle_id=plugin.bundle_id),
    )
    monkeypatch.setattr(registry, "_validate_plugin_metadata", lambda *_args: None)
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.external_plugin_registry.compute_plugin_folder_hash",
        lambda _path: plugin.folder_hash,
    )

    original_replace = Path.replace

    def _replace_with_failure(self: Path, target: Path) -> Path:
        if self.name == "install-test-plugin":
            raise OSError("swap failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _replace_with_failure)

    try:
        asyncio.run(registry.install_plugin(source.source_id, plugin.bundle_id))
    except ExternalPluginError as exc:
        assert "Could not install plugin test-plugin" in str(exc)
    else:
        raise AssertionError("install_plugin should fail when the final swap fails.")

    assert existing_install.exists()
    assert (existing_install / "version.txt").read_text(encoding="utf-8") == "old"
    assert not (registry.installed_dir / f"{plugin.bundle_id}-backup").exists()


def test_fetch_bytes_uses_proxy_for_requests_timeout_and_proxies(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Response:
        content = b"ok"

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url: str, headers: dict[str, str], timeout: float, proxies: dict[str, str] | None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["proxies"] = proxies
        return _Response()

    monkeypatch.setattr("bitcoin_safe.network_utils.requests.get", _fake_get)

    proxy_info = ProxyInfo.parse("socks5h://127.0.0.1:9050")
    result = fetch_bytes("https://dummy.example/source.toml", headers={"X-Test": "1"}, proxy_info=proxy_info)

    assert result == b"ok"
    assert captured["url"] == "https://dummy.example/source.toml"
    assert captured["headers"] == {"X-Test": "1"}
    assert captured["timeout"] == 10
    assert captured["proxies"] == {
        "http": "socks5h://127.0.0.1:9050",
        "https": "socks5h://127.0.0.1:9050",
    }


def test_external_registry_fetch_and_verify_manifest_uses_proxy_info(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path)
    config.network_config.proxy_url = "socks5h://127.0.0.1:9050"
    registry = ExternalPluginRegistry(
        PluginRuntimeContext(
            wallet_functions=WalletFunctions(Signals()),
            config=config,
            fx=_DummyFX(),
            loop_in_thread=None,
            subscription_price_lookup=None,
            parent=None,
        )
    )
    manifest = VerifiedPluginSourceManifest(
        source_id="test-source",
        display_name="Test Source",
        source_serial=1,
        signer_fingerprint="fingerprint",
        manifest_url="https://dummy.example/source.toml",
        plugins=tuple(),
    )
    captured_proxy_infos: list[ProxyInfo | None] = []

    def _fake_fetch_bytes(url: str, headers: dict[str, str], proxy_info: ProxyInfo | None) -> bytes:
        del headers
        captured_proxy_infos.append(proxy_info)
        if url.endswith(".asc"):
            return b"signature"
        return b'schema_version = "1"\nsource_id = "test-source"\ndisplay_name = "Test Source"\nsource_serial = 1\n'

    class _FakeVerifier:
        def __init__(self, list_of_known_keys, proxies) -> None:
            del list_of_known_keys, proxies

        def import_public_key_block(self, public_key_block: str) -> SimpleNamespace:
            del public_key_block
            return SimpleNamespace(fingerprint="A" * 40)

        def verify_detached_signature_with_fingerprint(
            self, binary_file: Path, signature_file: Path
        ) -> tuple[bool, str]:
            del binary_file, signature_file
            return True, "A" * 40

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.external_plugin_registry.fetch_bytes", _fake_fetch_bytes
    )
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.external_plugin_registry.SignatureVerifyer", _FakeVerifier
    )
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.external_plugin_registry.pgpy.PGPSignature.from_blob",
        lambda _blob: (_ for _ in ()).throw(ValueError("no parse")),
    )
    monkeypatch.setattr(
        registry,
        "_parse_source_manifest",
        lambda _text, manifest_url: replace(manifest, manifest_url=manifest_url),
    )
    monkeypatch.setattr(
        registry, "_resolve_source_catalog", lambda parsed_manifest, _auth_config: (parsed_manifest, {})
    )

    fetched_manifest, _manifest_bytes, _signature_bytes, _metadata_texts = (
        registry._fetch_and_verify_manifest(
            manifest_url="https://dummy.example/source.toml",
            pinned_source_public_key="public-key",
            auth_config=PluginSourceAuthConfig(),
            last_seen_source_serial=0,
        )
    )

    assert fetched_manifest.source_id == "test-source"
    assert len(captured_proxy_infos) == 2
    assert all(proxy_info is not None for proxy_info in captured_proxy_infos)
    assert all(
        proxy_info and proxy_info.get_url() == "socks5h://127.0.0.1:9050"
        for proxy_info in captured_proxy_infos
    )


def test_external_registry_remote_metadata_and_archive_fetches_use_proxy_info(
    tmp_path: Path, monkeypatch
) -> None:
    config = _make_config(tmp_path)
    config.network_config.proxy_url = "socks5h://127.0.0.1:9050"
    registry = ExternalPluginRegistry(
        PluginRuntimeContext(
            wallet_functions=WalletFunctions(Signals()),
            config=config,
            fx=_DummyFX(),
            loop_in_thread=None,
            subscription_price_lookup=None,
            parent=None,
        )
    )
    plugin = ExternalPluginCatalogEntry(
        source_id="test-source",
        source_display_name="Test Source",
        bundle_id="test-plugin",
        version="1.0.0",
        display_name="Test Plugin",
        description="Test description",
        provider="Tests",
        entrypoint="test_plugin/plugin_bundle.py",
        plugin_api_version="1",
        app_version_specifier=">=0.0.0",
        folder_hash="new-hash",
        release_ref="main",
    )
    source = PluginSource(
        source_id="test-source",
        display_name="Test Source",
        manifest_url="https://dummy.example/org/repo/raw/branch/main/source.toml",
        pinned_source_public_key="key",
        auth_config=PluginSourceAuthConfig(),
    )
    prepared_plugin_dir = tmp_path / "prepared-plugin"
    prepared_plugin_dir.mkdir()
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    captured_calls: list[tuple[str, ProxyInfo | None]] = []

    def _fake_fetch_bytes(url: str, headers: dict[str, str], proxy_info: ProxyInfo | None) -> bytes:
        del headers
        captured_calls.append((url, proxy_info))
        if url.endswith("pyproject.toml"):
            return _plugin_pyproject_text().encode("utf-8")
        return b"zip-bytes"

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.external_plugin_registry.fetch_bytes", _fake_fetch_bytes
    )
    monkeypatch.setattr(
        registry,
        "_extract_zip_safely",
        lambda _zip_path, extract_root: extract_root.mkdir(parents=True, exist_ok=True),
    )
    monkeypatch.setattr(
        registry, "_find_plugin_directory", lambda _root_dir, _plugin_path: prepared_plugin_dir
    )

    metadata = registry._fetch_plugin_metadata(
        manifest_url=source.manifest_url,
        auth_config=source.auth_config,
        bundle_id=plugin.bundle_id,
    )
    plugin_dir = registry._prepare_plugin_directory(source=source, plugin=plugin, temp_dir=temp_dir)

    assert metadata.bundle_id == "test-plugin"
    assert plugin_dir == prepared_plugin_dir
    assert len(captured_calls) == 2
    assert captured_calls[0][0].endswith("/plugins/test-plugin/pyproject.toml")
    assert captured_calls[1][0].endswith("/archive/main.zip")
    assert all(proxy_info is not None for _, proxy_info in captured_calls)
    assert all(
        proxy_info and proxy_info.get_url() == "socks5h://127.0.0.1:9050" for _, proxy_info in captured_calls
    )


def test_external_registry_refresh_sources_caches_plugin_metadata_for_local_catalog(
    tmp_path: Path, monkeypatch
) -> None:
    registry = ExternalPluginRegistry(_make_runtime_context(tmp_path))
    source = PluginSource(
        source_id="test-source",
        display_name="Test Source",
        manifest_url="https://dummy.example/source.toml",
        pinned_source_public_key="key",
        auth_config=PluginSourceAuthConfig(),
        enabled=True,
        last_seen_source_serial=0,
    )
    registry._write_source(source)
    source_toml = "\n".join(
        [
            'schema_version = "1"',
            'source_id = "test-source"',
            'display_name = "Test Source"',
            "source_serial = 1",
            "",
            "[[plugins]]",
            'bundle_id = "test-plugin"',
            'folder_hash = "hash"',
            'release_ref = "main"',
            "",
        ]
    )

    def _fake_fetch_bytes(url: str, headers: dict[str, str], proxy_info: ProxyInfo | None) -> bytes:
        del headers, proxy_info
        if url.endswith(".asc"):
            return b"signature"
        if url.endswith("pyproject.toml"):
            return _plugin_pyproject_text().encode("utf-8")
        return source_toml.encode("utf-8")

    class _FakeVerifier:
        def __init__(self, list_of_known_keys, proxies) -> None:
            del list_of_known_keys, proxies

        def import_public_key_block(self, public_key_block: str) -> SimpleNamespace:
            del public_key_block
            return SimpleNamespace(fingerprint="A" * 40)

        def verify_detached_signature_with_fingerprint(
            self, binary_file: Path, signature_file: Path
        ) -> tuple[bool, str]:
            del binary_file, signature_file
            return True, "A" * 40

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.external_plugin_registry.fetch_bytes", _fake_fetch_bytes
    )
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.external_plugin_registry.SignatureVerifyer", _FakeVerifier
    )
    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.external_plugin_registry.pgpy.PGPSignature.from_blob",
        lambda _blob: (_ for _ in ()).throw(ValueError("no parse")),
    )

    refreshed = asyncio.run(registry.refresh_sources(recheck_installed=False))
    assert len(refreshed) == 1

    def _fail_fetch_bytes(url: str, headers: dict[str, str], proxy_info: ProxyInfo | None) -> bytes:
        del headers, proxy_info
        raise AssertionError(f"Unexpected network fetch for {url}")

    monkeypatch.setattr(
        "bitcoin_safe.plugin_framework.external_plugin_registry.fetch_bytes", _fail_fetch_bytes
    )

    entries = registry.list_available_plugins()

    assert len(entries) == 1
    assert entries[0].bundle_id == "test-plugin"
    assert entries[0].display_name == "Test Plugin"
    assert entries[0].version == "1.0.0"


def test_external_registry_load_module_reloads_changed_plugin_package_modules(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "bundle"
    package_dir = plugin_dir / "test_plugin"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "client.py").write_text('VALUE = "old"\n', encoding="utf-8")
    (package_dir / "plugin_bundle.py").write_text(
        "\n".join(
            [
                "from test_plugin.client import VALUE",
                "",
                "VALUE_FROM_CLIENT = VALUE",
                "",
            ]
        ),
        encoding="utf-8",
    )

    first_module = ExternalPluginRegistry._load_module(
        "bitcoin_safe_external_plugin_test_plugin_old_hash",
        package_dir / "plugin_bundle.py",
        plugin_dir,
    )

    assert first_module.VALUE_FROM_CLIENT == "old"

    (package_dir / "client.py").write_text('VALUE = "new value from update"\n', encoding="utf-8")

    second_module = ExternalPluginRegistry._load_module(
        "bitcoin_safe_external_plugin_test_plugin_new_hash",
        package_dir / "plugin_bundle.py",
        plugin_dir,
    )

    assert second_module.VALUE_FROM_CLIENT == "new value from update"


def test_external_registry_load_module_isolates_top_level_import_aliases(tmp_path: Path) -> None:
    first_plugin_dir = tmp_path / "bundle-one"
    first_package_dir = first_plugin_dir / "first_plugin"
    first_package_dir.mkdir(parents=True)
    (first_package_dir / "__init__.py").write_text("", encoding="utf-8")
    (first_plugin_dir / "helper.py").write_text('VALUE = "ONE"\n', encoding="utf-8")
    (first_package_dir / "plugin_bundle.py").write_text(
        "\n".join(
            [
                "import helper",
                "",
                "VALUE_FROM_HELPER = helper.VALUE",
                "",
            ]
        ),
        encoding="utf-8",
    )

    second_plugin_dir = tmp_path / "bundle-two"
    second_package_dir = second_plugin_dir / "second_plugin"
    second_package_dir.mkdir(parents=True)
    (second_package_dir / "__init__.py").write_text("", encoding="utf-8")
    (second_plugin_dir / "helper.py").write_text('VALUE = "TWO"\n', encoding="utf-8")
    (second_package_dir / "plugin_bundle.py").write_text(
        "\n".join(
            [
                "import helper",
                "",
                "VALUE_FROM_HELPER = helper.VALUE",
                "",
            ]
        ),
        encoding="utf-8",
    )

    original_sys_path = sys.path[:]
    try:
        first_module = ExternalPluginRegistry._load_module(
            "bitcoin_safe_external_plugin_first_plugin_hash",
            first_package_dir / "plugin_bundle.py",
            first_plugin_dir,
        )
        second_module = ExternalPluginRegistry._load_module(
            "bitcoin_safe_external_plugin_second_plugin_hash",
            second_package_dir / "plugin_bundle.py",
            second_plugin_dir,
        )

        assert first_module.VALUE_FROM_HELPER == "ONE"
        assert second_module.VALUE_FROM_HELPER == "TWO"
        assert "helper" not in sys.modules
        assert str(first_plugin_dir.resolve()) not in sys.path
        assert str(second_plugin_dir.resolve()) not in sys.path
    finally:
        sys.path[:] = original_sys_path
        sys.modules.pop("bitcoin_safe_external_plugin_first_plugin_hash", None)
        sys.modules.pop("bitcoin_safe_external_plugin_second_plugin_hash", None)


def test_external_registry_persists_structured_catalog_with_btcpay_config(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    source = PluginSource(
        source_id="test-source",
        display_name="Test Source",
        manifest_url="https://dummy.example/source.toml",
        pinned_source_public_key="key",
        auth_config=PluginSourceAuthConfig(kind="bearer", bearer_token="secret-token"),
        enabled=True,
        last_seen_source_serial=1,
    )
    catalog_entry = ExternalPluginCatalogEntry(
        source_id=source.source_id,
        source_display_name=source.display_name,
        bundle_id="test-plugin",
        version="1.0.0",
        display_name="Test Plugin",
        description="Test description",
        provider="Tests",
        entrypoint="test_plugin/plugin_bundle.py",
        plugin_api_version="1",
        app_version_specifier=">=0.0.0",
        folder_hash="hash",
        release_ref="main",
        btcpay_config=_btcpay_config(),
        installed_version="derived",
        installed_folder_hash="derived",
        update_available=True,
    )
    registry = ExternalPluginRegistry(config)
    registry.sources[source.source_id] = source
    registry.source_catalogs[source.source_id] = VerifiedPluginSourceManifest(
        source_id=source.source_id,
        display_name=source.display_name,
        source_serial=1,
        signer_fingerprint="fingerprint",
        manifest_url=source.manifest_url,
        plugins=(catalog_entry,),
    )
    registry.installed_plugins[catalog_entry.bundle_id] = _installed_source_plugin_metadata(
        source.source_id,
        catalog_entry.bundle_id,
    )

    registry.save()
    loaded = ExternalPluginRegistry.from_config(config)
    loaded_entry = loaded.source_catalogs[source.source_id].plugins[0]

    assert registry.repository_path.exists()
    assert isinstance(loaded.load_source(source.source_id).auth_config, PluginSourceAuthConfig)
    assert loaded.load_source(source.source_id).auth_config.kind == "bearer"
    assert loaded.load_source(source.source_id).auth_config.bearer_token == "secret-token"
    assert loaded_entry.btcpay_config is not None
    assert loaded_entry.btcpay_config.npub_bitcoin_safe_pos == _btcpay_config().npub_bitcoin_safe_pos
    assert loaded_entry.installed_version is None
    assert loaded.load_installed_metadata()[catalog_entry.bundle_id].source_id == source.source_id


def test_resolve_external_plugin_package_root_source_mode(tmp_path: Path) -> None:
    package_root = tmp_path / "test_plugin"
    package_root.mkdir()
    module_file = package_root / "client.py"
    module_file.write_text("", encoding="utf-8")

    resolved = resolve_external_plugin_package_root(str(module_file), "test_plugin")

    assert resolved == package_root


def test_resolve_external_plugin_package_root_bytecode_mode(tmp_path: Path) -> None:
    package_root = tmp_path / "test_plugin"
    module_file = package_root / "_bytecode" / "cpython-312" / "test_plugin" / "client.pyc"
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_bytes(b"")

    resolved = resolve_external_plugin_package_root(str(module_file), "test_plugin")

    assert resolved == package_root


def test_external_plugin_resources_exposes_icons_dir_from_package_root(tmp_path: Path) -> None:
    package_root = tmp_path / "test_plugin"
    _write_minimal_plugin_manifest(package_root)
    icons_dir = package_root / "icons"
    (package_root / "locales").mkdir(parents=True)
    icons_dir.mkdir(parents=True, exist_ok=True)
    module_file = package_root / "_bytecode" / "cpython-312" / "test_plugin" / "client.pyc"
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_bytes(b"")
    _write_plugin_svg(icons_dir / "bell.svg")

    config = _make_config(tmp_path)
    resources = ExternalPluginResources(str(module_file), "test_plugin", config)

    try:
        assert resources.icons_dir == icons_dir
    finally:
        resources.close()


def test_load_external_plugin_btcpay_config_from_source_manifest(tmp_path: Path) -> None:
    package_root = tmp_path / "test_plugin"
    package_root.mkdir()
    module_file = package_root / "client.py"
    module_file.write_text("", encoding="utf-8")
    (package_root / "plugin.yaml").write_text(
        "\n".join(
            [
                'schema_version: "1"',
                'bundle_id: "test-plugin"',
                'version: "0.1.0"',
                'display_name: "Test Plugin"',
                'description: "Test plugin"',
                "authors:",
                '  - "Tests <tests@example.com>"',
                'provider: "Tests"',
                'plugin_api_version: "1"',
                'entrypoint: "test_plugin/plugin_bundle.py"',
                'bitcoin_safe_version: ">=0.0.0,<999.0.0"',
                'python: ">=3.10,<3.13"',
                "btcpay:",
                "  btcpay_base:",
                '    base_url: "https://testnet.demo.btcpayserver.org"',
                '    pos_app_id: "3sgZmTZfKP8mRQciCqNh6g5F1G1s"',
                '    store_id: "98rXQCLFR3jmjbh5V5BomnqKJT5xC9kYejFRJHfmLWBq"',
                "  client:",
                '    npub_bitcoin_safe_pos: "npub150ncc39ala3h9zudddrjqy9f7wenp7d20rjm99wchwtkdpze07wqukr9cu"',
                "  products:",
                "    demo-plugin:",
                '      - offering_id: "offering_89j5mBhvUYuvFfxNL1"',
                '        plan_id: "plan_Bqm6FpomH4TvZLj113"',
                '        pos_id: "demo-plugin"',
                '        trial_pos_id: "demo-plugin-trial"',
                '        duration: "month"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = load_external_plugin_btcpay_config(package_root)

    assert config.btcpay_base.store_id == "98rXQCLFR3jmjbh5V5BomnqKJT5xC9kYejFRJHfmLWBq"
    assert config.resolve_subscription("demo-plugin", "month").plan_id == "plan_Bqm6FpomH4TvZLj113"


def test_load_external_plugin_btcpay_config_from_bytecode_pyproject(tmp_path: Path) -> None:
    bundle_root = tmp_path / "bundle"
    package_root = bundle_root / "test_plugin"
    module_file = package_root / "_bytecode" / "cpython-312" / "test_plugin" / "client.pyc"
    module_file.parent.mkdir(parents=True, exist_ok=True)
    module_file.write_bytes(b"")
    (bundle_root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[tool.poetry]",
                'name = "test-plugin"',
                'version = "0.1.0"',
                "",
                "[tool.bitcoin_safe.plugin]",
                'entrypoint = "test_plugin/plugin_bundle.py"',
                'plugin_api_version = "1"',
                'bitcoin_safe_version = ">=0.0.0,<999.0.0"',
                'provider = "Tests"',
                "",
                "[tool.bitcoin_safe.plugin.btcpay.btcpay_base]",
                'base_url = "https://testnet.demo.btcpayserver.org"',
                'pos_app_id = "3sgZmTZfKP8mRQciCqNh6g5F1G1s"',
                'store_id = "98rXQCLFR3jmjbh5V5BomnqKJT5xC9kYejFRJHfmLWBq"',
                "",
                "[tool.bitcoin_safe.plugin.btcpay.client]",
                'npub_bitcoin_safe_pos = "npub150ncc39ala3h9zudddrjqy9f7wenp7d20rjm99wchwtkdpze07wqukr9cu"',
                "",
                "[[tool.bitcoin_safe.plugin.btcpay.products.demo-plugin]]",
                'offering_id = "offering_89j5mBhvUYuvFfxNL1"',
                'plan_id = "plan_Bqm6FpomH4TvZLj113"',
                'pos_id = "demo-plugin"',
                'trial_pos_id = "demo-plugin-trial"',
                'duration = "month"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = load_external_plugin_btcpay_config(package_root)

    assert config.btcpay_base.store_id == "98rXQCLFR3jmjbh5V5BomnqKJT5xC9kYejFRJHfmLWBq"
    assert config.resolve_subscription("demo-plugin", "month").plan_id == "plan_Bqm6FpomH4TvZLj113"


def test_external_plugin_resources_reload_translator_installs_matching_qm(
    qapp: QApplication, tmp_path: Path
) -> None:
    del qapp
    package_root = tmp_path / "test_plugin"
    _write_minimal_plugin_manifest(package_root)
    locales_dir = package_root / "locales"
    locales_dir.mkdir(parents=True)
    module_file = package_root / "client.py"
    module_file.write_text("", encoding="utf-8")
    source_qm = Path(__file__).resolve().parents[2] / "bitcoin_safe" / "gui" / "locales" / "app_de_DE.qm"
    (locales_dir / "app_de_DE.qm").write_bytes(source_qm.read_bytes())

    config = _make_config(tmp_path)
    config.language_code = "de_DE"
    resources = ExternalPluginResources(str(module_file), "test_plugin", config)

    try:
        assert resources._translator is not None
    finally:
        resources.close()
        assert resources._translator is None


def test_external_plugin_resources_reload_translator_falls_back_to_package_prefix(
    qapp: QApplication, tmp_path: Path
) -> None:
    del qapp
    package_root = tmp_path / "test_plugin"
    _write_minimal_plugin_manifest(package_root)
    locales_dir = package_root / "locales"
    locales_dir.mkdir(parents=True)
    module_file = package_root / "client.py"
    module_file.write_text("", encoding="utf-8")
    source_qm = Path(__file__).resolve().parents[2] / "bitcoin_safe" / "gui" / "locales" / "app_de_DE.qm"
    (locales_dir / "test_plugin_de_DE.qm").write_bytes(source_qm.read_bytes())

    config = _make_config(tmp_path)
    config.language_code = "de_DE"
    resources = ExternalPluginResources(str(module_file), "test_plugin", config)

    try:
        assert resources._translator is not None
    finally:
        resources.close()
        assert resources._translator is None


def test_external_plugin_resources_reload_translator_skips_missing_qm(
    qapp: QApplication, tmp_path: Path
) -> None:
    del qapp
    package_root = tmp_path / "test_plugin"
    _write_minimal_plugin_manifest(package_root)
    (package_root / "locales").mkdir(parents=True)
    module_file = package_root / "client.py"
    module_file.write_text("", encoding="utf-8")

    config = _make_config(tmp_path)
    config.language_code = "de_DE"
    resources = ExternalPluginResources(str(module_file), "test_plugin", config)

    try:
        assert resources._translator is None
    finally:
        resources.close()


def test_external_plugin_resources_reload_translator_replaces_existing_translator(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    package_root = tmp_path / "test_plugin"
    _write_minimal_plugin_manifest(package_root)
    locales_dir = package_root / "locales"
    locales_dir.mkdir(parents=True)
    module_file = package_root / "client.py"
    module_file.write_text("", encoding="utf-8")
    source_dir = Path(__file__).resolve().parents[2] / "bitcoin_safe" / "gui" / "locales"
    (locales_dir / "app_de_DE.qm").write_bytes((source_dir / "app_de_DE.qm").read_bytes())
    (locales_dir / "app_fr_FR.qm").write_bytes((source_dir / "app_fr_FR.qm").read_bytes())

    installed: list[object] = []
    removed: list[object] = []

    def _install_translator(_app: QApplication, translator: object) -> bool:
        installed.append(translator)
        return True

    def _remove_translator(_app: QApplication, translator: object) -> bool:
        removed.append(translator)
        return True

    monkeypatch.setattr(QApplication, "installTranslator", _install_translator)
    monkeypatch.setattr(QApplication, "removeTranslator", _remove_translator)

    config = _make_config(tmp_path)
    config.language_code = "de_DE"
    resources = ExternalPluginResources(str(module_file), "test_plugin", config)

    try:
        first_translator = resources._translator
        assert first_translator is not None
        assert installed == [first_translator]
        assert removed == []

        config.language_code = "fr_FR"
        resources.reload_translator()

        assert removed == [first_translator]
        assert resources._translator is not None
        assert resources._translator is not first_translator
        assert installed[-1] is resources._translator
    finally:
        resources.close()


def test_plugin_widget_update_ui_refreshes_runtime_metadata(qapp: QApplication) -> None:
    del qapp
    client = _DisplayMetadataPluginClient()
    widget = client.create_plugin_widget()
    initial_pixmap = widget.icon_label.pixmap()
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor("red"))
    icon = QIcon(pixmap)

    client.set_display_metadata(
        title="Updated Plugin",
        description="Updated description",
        provider="Updated provider",
        icon=icon,
    )
    widget.updateUi()

    assert client.node.title == "Updated Plugin"
    assert widget.title_label.text() == "<b>Updated Plugin</b>"
    assert widget.provider_label.text() == "Provided by: Updated provider"
    assert widget.description_label.text() == "Updated description"
    assert initial_pixmap is not None
    assert initial_pixmap.isNull()
    assert widget.icon_label.pixmap() is not None
    assert not widget.icon_label.pixmap().isNull()
    assert client.icon.cacheKey() == icon.cacheKey()

    widget.close()
    client.close()


def test_plugin_manager_refreshes_client_translators_on_language_switch(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp

    def _empty_external_state(cls, context, external_registry):
        del cls, context, external_registry
        return {}

    monkeypatch.setattr(PluginManager, "_refresh_external_state", classmethod(_empty_external_state))
    config = _make_config(tmp_path)
    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    client = _TrackingPluginClient()
    manager = PluginManager(
        wallet_functions=wallet_functions,
        config=config,
        fx=_DummyFX(),
        loop_in_thread=None,
        external_registry=ExternalPluginRegistry(config),
        clients=[client, _DisplayMetadataPluginClient()],
        parent=None,
    )

    try:
        signals.language_switch.emit()

        assert client.reload_translator_calls == 1
        assert client.update_ui_calls == 1
    finally:
        manager.close()


def test_external_plugin_widget_enables_update_button_while_enabled(qapp: QApplication) -> None:
    del qapp
    client = _DisplayMetadataPluginClient()
    client.set_plugin_identity(
        plugin_source=PluginClientSource.EXTERNAL,
        plugin_bundle_id="test-plugin",
    )
    client.set_external_state(
        update_available=True,
        installed_version="1.0.0",
        available_version="9.9.9",
        available_hash="new-hash-long",
    )
    widget = client.create_plugin_widget()

    try:
        update_button = widget.update_button
        assert not update_button.isHidden()
        assert update_button.isEnabled()
        assert widget.version_label.parentWidget() is widget.metadata_row
        assert widget.provider_label.parentWidget() is widget.metadata_row
        assert widget.metadata_layout.itemAt(0).widget() is widget.version_label
        assert widget.metadata_layout.itemAt(1).widget() is widget.metadata_separator_label
        assert widget.metadata_layout.itemAt(2).widget() is widget.provider_label
        assert widget.version_label.text() == "Version 1.0.0"
        assert not widget.metadata_separator_label.isHidden()
        assert update_button.text() == "Update to 9.9.9 (hash: new-hash)"

        client.set_enabled(False)
        widget.updateUi()

        assert not update_button.isHidden()
        assert update_button.isEnabled()
    finally:
        widget.close()
        client.close()


def test_external_plugin_widget_orders_action_buttons_left_to_right(qapp: QApplication) -> None:
    del qapp
    client = _DisplayMetadataPluginClient()
    client.set_plugin_identity(
        plugin_source=PluginClientSource.EXTERNAL,
        plugin_bundle_id="test-plugin",
    )
    client.set_external_state(
        update_available=True,
        installed_version="1.0.0",
        available_version="9.9.9",
        available_hash="new-hash",
    )
    client.set_enabled(False)
    widget = client.create_plugin_widget()

    try:
        assert isinstance(widget.management_layout, QHBoxLayout)
        assert widget.management_layout.itemAt(0).widget() is widget.management_buttons_container
        assert widget.management_layout.itemAt(1).spacerItem() is not None
        assert widget.management_layout.itemAt(2).widget() is widget.destructive_buttons_container
        assert not widget.update_button.isHidden()
        assert widget.delete_button.parentWidget() is widget.action_buttons_container
        assert isinstance(widget.action_buttons_layout, QVBoxLayout)
        assert widget.action_buttons_layout.itemAt(0).widget() is widget.delete_button
        assert not widget.delete_button.isHidden()
    finally:
        widget.close()
        client.close()


def test_source_catalog_item_widget_shows_versions_in_status_and_button(qapp: QApplication) -> None:
    del qapp
    item = SourceCatalogItem(
        entry=ExternalPluginCatalogEntry(
            source_id="test-source",
            source_display_name="Test Source",
            bundle_id="test-plugin",
            version="2.0.0",
            display_name="Test Plugin",
            description="Test description",
            provider="Tests",
            entrypoint="test_plugin/plugin_bundle.py",
            plugin_api_version="1",
            app_version_specifier=">=0.0.0",
            folder_hash="hash",
            release_ref="main",
            update_available=True,
            installed_version="1.0.0",
        ),
        parent=None,
    )
    widget = item.create_plugin_widget()

    try:
        assert widget.version_label.text() == "Version 1.0.0 -> 2.0.0 (hash: hash)"
        assert widget.install_button.text() == "Update to 2.0.0 (hash: hash)"
    finally:
        widget.close()


def test_source_catalog_item_widget_uses_spinning_install_button(qapp: QApplication) -> None:
    del qapp
    item = SourceCatalogItem(
        entry=ExternalPluginCatalogEntry(
            source_id="test-source",
            source_display_name="Test Source",
            bundle_id="test-plugin",
            version="2.0.0",
            display_name="Test Plugin",
            description="Test description",
            provider="Tests",
            entrypoint="test_plugin/plugin_bundle.py",
            plugin_api_version="1",
            app_version_specifier=">=0.0.0",
            folder_hash="hash",
            release_ref="main",
        ),
        parent=None,
    )
    widget = item.create_plugin_widget()

    try:
        assert isinstance(widget.install_button, SpinningButton)
    finally:
        widget.close()


def test_external_registry_marks_hash_only_plugin_change_as_update(tmp_path: Path, monkeypatch) -> None:
    config = _make_config(tmp_path)
    registry = ExternalPluginRegistry(
        PluginRuntimeContext(
            wallet_functions=WalletFunctions(Signals()),
            config=config,
            fx=_DummyFX(),
            loop_in_thread=None,
            subscription_price_lookup=None,
            parent=None,
        )
    )
    source = PluginSource(
        source_id="test-source",
        display_name="Test Source",
        manifest_url="https://dummy.example/source.toml",
        pinned_source_public_key="key",
        auth_config=PluginSourceAuthConfig(),
    )
    plugin = ExternalPluginCatalogEntry(
        source_id="test-source",
        source_display_name="Test Source",
        bundle_id="test-plugin",
        version="1.0.0",
        display_name="Test Plugin",
        description="Test description",
        provider="Tests",
        entrypoint="test_plugin/plugin_bundle.py",
        plugin_api_version="1",
        app_version_specifier=">=0.0.0",
        folder_hash="new-hash",
        release_ref="main",
    )
    manifest = VerifiedPluginSourceManifest(
        source_id="test-source",
        display_name="Test Source",
        source_serial=1,
        signer_fingerprint="fingerprint",
        manifest_url=source.manifest_url,
        plugins=(plugin,),
    )
    installed_metadata = InstalledSourcePluginMetadata(
        bundle_id="test-plugin",
        source_id="test-source",
        version="1.0.0",
        folder_hash="old-hash",
        installed_at="2026-04-21T00:00:00+00:00",
        trusted_auto_allow_signer=False,
        verified_signer_fingerprint="fingerprint",
    )

    monkeypatch.setattr(registry, "load_sources", lambda: [source])
    monkeypatch.setattr(
        registry,
        "load_cached_source_catalog",
        lambda source_id: manifest if source_id == source.source_id else None,
    )
    monkeypatch.setattr(registry, "load_installed_metadata", lambda: {plugin.bundle_id: installed_metadata})

    entries = registry.list_available_plugins()

    assert len(entries) == 1
    assert entries[0].update_available is True
    assert entries[0].installed_version == "1.0.0"
    assert entries[0].installed_folder_hash == "old-hash"


def test_settings_tabs_refresh_on_language_switch(qapp: QApplication, tmp_path: Path) -> None:
    del qapp
    config = _make_config(tmp_path)
    signals = Signals()
    language_chooser = LanguageChooser(
        config=config,
        signals_language_switch=[signals.language_switch],
        signals_currency_switch=signals.currency_switch,
        parent=None,
    )
    settings = Settings(
        config=config,
        signals=signals,
        language_chooser=language_chooser,
        fx=_DummyFX(),
        parent=None,
    )

    try:
        settings.setTabText(settings.indexOf(settings.about_tab), "changed")
        settings.setTabText(settings.indexOf(settings.langauge_ui), "changed")
        settings.setTabText(settings.indexOf(settings.network_settings_ui), "changed")

        signals.language_switch.emit()

        assert settings.tabText(settings.indexOf(settings.about_tab)) == "About"
        assert settings.tabText(settings.indexOf(settings.langauge_ui)) == "General"
        assert settings.tabText(settings.indexOf(settings.network_settings_ui)) == "Network"
    finally:
        settings.close()


def test_plugin_manager_updates_enabled_plugin_by_reloading_replacement(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp

    def _empty_external_state(cls, context, external_registry):
        del cls, context, external_registry
        return {}

    monkeypatch.setattr(PluginManager, "_refresh_external_state", classmethod(_empty_external_state))

    config = _make_config(tmp_path)
    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    loop_in_thread = _ImmediateLoopInThread()
    current_client = _LoadTrackingPluginClient(enabled=True)
    current_client.set_plugin_identity(
        plugin_source=PluginClientSource.EXTERNAL,
        plugin_bundle_id="test-plugin",
    )
    replacement_client = _LoadTrackingPluginClient(enabled=False)
    replacement_client.set_plugin_identity(
        plugin_source=PluginClientSource.EXTERNAL,
        plugin_bundle_id="test-plugin",
    )
    manager = PluginManager(
        wallet_functions=wallet_functions,
        config=config,
        fx=_DummyFX(),
        loop_in_thread=loop_in_thread,
        external_registry=ExternalPluginRegistry(config),
        clients=[current_client],
        parent=None,
    )
    current_client.set_plugin_identity(
        plugin_source=PluginClientSource.EXTERNAL,
        plugin_bundle_id="test-plugin",
    )
    replacement_client.set_plugin_identity(
        plugin_source=PluginClientSource.EXTERNAL,
        plugin_bundle_id="test-plugin",
        plugin_id=current_client.plugin_id,
    )
    entry = ExternalPluginCatalogEntry(
        source_id="test-source",
        source_display_name="Test Source",
        bundle_id="test-plugin",
        version="2.0.0",
        display_name="Test Plugin",
        description="Test description",
        provider="Tests",
        entrypoint="test_plugin/plugin_bundle.py",
        plugin_api_version="1",
        app_version_specifier=">=0.0.0",
        folder_hash="new-hash",
        release_ref="main",
        update_available=True,
        installed_version="1.0.0",
    )
    install_calls: list[tuple[str, str]] = []

    try:

        async def _install_plugin(source_id: str, bundle_id: str) -> InstalledSourcePluginMetadata:
            install_calls.append((source_id, bundle_id))
            return _installed_source_plugin_metadata(
                source_id=source_id,
                bundle_id=bundle_id,
                version=entry.version,
                folder_hash=entry.folder_hash,
            )

        monkeypatch.setattr(
            manager.external_registry,
            "install_plugin",
            _install_plugin,
        )
        monkeypatch.setattr(manager, "_refresh_external_registry_state", lambda: True)

        def _refresh_after_registry_change(runtime_changed: bool) -> None:
            assert runtime_changed is True
            manager.clients = [replacement_client]

        monkeypatch.setattr(manager, "_refresh_after_registry_change", _refresh_after_registry_change)

        manager.update_installed_source_plugin(current_client, entry)

        assert install_calls == [("test-source", "test-plugin")]
        assert current_client.unload_calls == 1
        assert current_client.load_calls == 0
        assert replacement_client.enabled
        assert replacement_client.load_calls == 1
        assert loop_in_thread.calls[0]["key"] == "plugin_source_install:test-plugin"
        assert loop_in_thread.calls[0]["multiple_strategy"] == MultipleStrategy.REJECT_NEW_TASK
    finally:
        manager.close()


def test_plugin_manager_update_restores_paid_plugin_subscription_state(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp

    def _empty_external_state(cls, context, external_registry):
        del cls, context, external_registry
        return {}

    monkeypatch.setattr(PluginManager, "_refresh_external_state", classmethod(_empty_external_state))
    monkeypatch.setattr(
        PluginManager,
        "known_classes",
        {
            **PluginManager.known_classes,
            _PaidStateTrackingPluginClient.__name__: _PaidStateTrackingPluginClient,
        },
    )

    config = _make_config(tmp_path)
    loop_in_thread = _ImmediateLoopInThread()
    fx = _DummyFX()
    selected_plan = TEST_BTCPAY_SUBSCRIPTION_CONFIG.resolve_subscription("demo-plugin", PlanDuration.MONTH)
    current_client = _PaidStateTrackingPluginClient(
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        additional_access_providers=None,
        enabled=False,
        subscription_managers={
            selected_plan.plan_id: SubscriptionManager(
                config=config,
                loop_in_thread=loop_in_thread,
                subscription_product_key="demo-plugin",
                btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
                subscription_duration=selected_plan.duration,
                management_url="https://example.com/manage",
                stored_subscription_status=_stored_subscription_status(
                    SubscriptionManagementStatus(
                        status=SubscriptionManagementStatusCode.TRIAL,
                        phase=SubscriptionManagementPhase.TRIAL,
                        is_active=True,
                        is_suspended=False,
                    )
                ),
            )
        },
        selected_subscription_key=selected_plan.plan_id,
    )
    current_client.set_plugin_identity(
        plugin_source=PluginClientSource.EXTERNAL,
        plugin_bundle_id="test-plugin",
    )
    manager = PluginManager(
        wallet_functions=WalletFunctions(Signals()),
        config=config,
        fx=fx,
        loop_in_thread=loop_in_thread,
        external_registry=ExternalPluginRegistry(config),
        clients=[current_client],
        parent=None,
    )
    entry = ExternalPluginCatalogEntry(
        source_id="test-source",
        source_display_name="Test Source",
        bundle_id="test-plugin",
        version="2.0.0",
        display_name="Test Plugin",
        description="Test description",
        provider="Tests",
        entrypoint="test_plugin/plugin_bundle.py",
        plugin_api_version="1",
        app_version_specifier=">=0.0.0",
        folder_hash="new-hash",
        release_ref="main",
        update_available=True,
        installed_version="1.0.0",
    )

    try:

        async def _install_plugin(source_id: str, bundle_id: str) -> InstalledSourcePluginMetadata:
            return _installed_source_plugin_metadata(
                source_id=source_id,
                bundle_id=bundle_id,
                version=entry.version,
                folder_hash=entry.folder_hash,
            )

        monkeypatch.setattr(manager.external_registry, "install_plugin", _install_plugin)
        monkeypatch.setattr(manager, "_refresh_external_registry_state", lambda: True)

        def _refresh_after_registry_change(runtime_changed: bool) -> None:
            assert runtime_changed is True
            assert len(manager.serialized_client_dumps) == 1
            restored = PluginManager._restore_client_from_payload(
                manager.serialized_client_dumps[0],
                class_kwargs={
                    _PaidStateTrackingPluginClient.__name__: _PaidStateTrackingPluginClient.cls_kwargs(
                        config=config,
                        fx=fx,
                        loop_in_thread=loop_in_thread,
                        additional_access_providers=None,
                    ),
                    SubscriptionManager.__name__: SubscriptionManager.cls_kwargs(
                        config=config,
                        loop_in_thread=loop_in_thread,
                        btcpay_config=TEST_BTCPAY_SUBSCRIPTION_CONFIG,
                    ),
                },
            )
            assert isinstance(restored, _PaidStateTrackingPluginClient)
            manager.clients = [restored]

        monkeypatch.setattr(manager, "_refresh_after_registry_change", _refresh_after_registry_change)

        manager.update_installed_source_plugin(current_client, entry)

        replacement_client = manager.clients[0]
        assert isinstance(replacement_client, _PaidStateTrackingPluginClient)
        assert replacement_client.subscription_manager.management_url == "https://example.com/manage"
        assert replacement_client.subscription_manager.stored_subscription_status.status is not None
        assert (
            replacement_client.subscription_manager.stored_subscription_status.status.status
            == SubscriptionManagementStatusCode.TRIAL
        )
    finally:
        manager.close()


def test_plugin_manager_refresh_plugin_source_uses_background_task(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    loop_in_thread = _ImmediateLoopInThread()
    manager = PluginManager(
        **_plugin_manager_init_kwargs(tmp_path, loop_in_thread=loop_in_thread),
        parent=None,
    )
    refresh_threads: list[int] = []
    refreshed_states: list[bool] = []
    source = PluginSource(
        source_id="test-source",
        display_name="Test Source",
        manifest_url="https://example.invalid/source.toml",
        pinned_source_public_key="key",
        auth_config=PluginSourceAuthConfig(),
        enabled=True,
        last_seen_source_serial=1,
    )

    try:

        async def _refresh_sources(
            source_id: str | None = None,
            recheck_installed: bool = True,
            raise_on_error: bool = True,
        ) -> tuple[VerifiedPluginSourceManifest, ...]:
            del recheck_installed, raise_on_error
            refresh_threads.append(threading.get_ident())
            return (
                VerifiedPluginSourceManifest(
                    source_id=source.source_id,
                    display_name=source.display_name,
                    source_serial=2,
                    signer_fingerprint="fingerprint",
                    manifest_url=source.manifest_url,
                    plugins=(),
                ),
            )

        monkeypatch.setattr(
            manager.external_registry,
            "refresh_sources",
            _refresh_sources,
        )
        monkeypatch.setattr(manager, "_refresh_external_registry_state", lambda: False)
        monkeypatch.setattr(manager, "_refresh_after_registry_change", refreshed_states.append)

        manager.refresh_plugin_sources(source_id=source.source_id)

        assert refresh_threads
        assert refresh_threads[0] != threading.get_ident()
        assert refreshed_states == [False]
        assert loop_in_thread.calls[0]["key"] == f"plugin_source_refresh:{source.source_id}"
        assert loop_in_thread.calls[0]["multiple_strategy"] == MultipleStrategy.REJECT_NEW_TASK
    finally:
        manager.close()


def test_plugin_manager_manual_refresh_reports_errors_but_startup_refresh_is_silent(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    loop_in_thread = _ImmediateLoopInThread()
    manager = PluginManager(
        **_plugin_manager_init_kwargs(tmp_path, loop_in_thread=loop_in_thread),
        parent=None,
    )
    reported_errors: list[ExcInfo | Exception | None] = []

    try:

        async def _refresh_sources(
            source_id: str | None = None,
            recheck_installed: bool = True,
            raise_on_error: bool = True,
        ) -> tuple[VerifiedPluginSourceManifest, ...]:
            del source_id, recheck_installed, raise_on_error
            raise ExternalPluginError("boom")

        monkeypatch.setattr(manager.external_registry, "refresh_sources", _refresh_sources)
        monkeypatch.setattr(manager, "_show_async_registry_error", reported_errors.append)

        manager.refresh_plugin_sources(show_errors=False)
        assert reported_errors == []

        manager.refresh_plugin_sources()
        assert len(reported_errors) == 1
    finally:
        manager.close()


def test_plugin_manager_install_source_plugin_uses_background_task(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    loop_in_thread = _ImmediateLoopInThread()
    manager = PluginManager(
        **_plugin_manager_init_kwargs(tmp_path, loop_in_thread=loop_in_thread),
        parent=None,
    )
    install_threads: list[int] = []
    refreshed_states: list[bool] = []
    entry = ExternalPluginCatalogEntry(
        source_id="test-source",
        source_display_name="Test Source",
        bundle_id="test-plugin",
        version="1.0.0",
        display_name="Test Plugin",
        description="Test description",
        provider="Tests",
        entrypoint="test_plugin/plugin_bundle.py",
        plugin_api_version="1",
        app_version_specifier=">=0.0.0",
        folder_hash="hash",
        release_ref="main",
    )

    try:

        async def _install_plugin(source_id: str, bundle_id: str) -> InstalledSourcePluginMetadata:
            install_threads.append(threading.get_ident())
            return _installed_source_plugin_metadata(source_id=source_id, bundle_id=bundle_id)

        monkeypatch.setattr(
            manager.external_registry,
            "install_plugin",
            _install_plugin,
        )
        monkeypatch.setattr(manager, "_refresh_external_registry_state", lambda: False)
        monkeypatch.setattr(manager, "_refresh_after_registry_change", refreshed_states.append)

        manager.install_source_plugin(entry)

        assert install_threads
        assert install_threads[0] != threading.get_ident()
        assert refreshed_states == [False]
        assert loop_in_thread.calls[0]["key"] == "plugin_source_install:test-plugin"
        assert loop_in_thread.calls[0]["multiple_strategy"] == MultipleStrategy.REJECT_NEW_TASK
    finally:
        manager.close()


def test_plugin_manager_schedules_startup_source_refresh_when_sources_exist(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    source = PluginSource(
        source_id="test-source",
        display_name="Test Source",
        manifest_url="https://example.invalid/source.toml",
        pinned_source_public_key="key",
        auth_config=PluginSourceAuthConfig(),
        enabled=True,
        last_seen_source_serial=1,
    )

    monkeypatch.setattr(ExternalPluginRegistry, "load_sources", lambda self: [source])
    manager = PluginManager(
        **_plugin_manager_init_kwargs(tmp_path, loop_in_thread=_ImmediateLoopInThread()),
        parent=None,
    )

    try:
        assert manager._startup_source_refresh_timer is not None
        assert manager._startup_source_refresh_timer.isSingleShot()
        assert manager._startup_source_refresh_timer.interval() == 60_000
        assert manager._startup_source_refresh_timer.isActive()
        assert manager.external_registry.last_download_time is None
    finally:
        manager.close()


def test_plugin_manager_uses_injected_external_registry(qapp: QApplication, tmp_path: Path) -> None:
    del qapp
    config = _make_config(tmp_path)
    external_registry = ExternalPluginRegistry(config)
    first_manager = PluginManager(
        wallet_functions=WalletFunctions(Signals()),
        config=config,
        fx=_DummyFX(),
        loop_in_thread=None,
        external_registry=external_registry,
        parent=None,
    )
    second_manager = PluginManager(
        wallet_functions=WalletFunctions(Signals()),
        config=config,
        fx=_DummyFX(),
        loop_in_thread=None,
        external_registry=external_registry,
        parent=None,
    )

    try:
        assert first_manager.external_registry is external_registry
        assert second_manager.external_registry is external_registry
        assert "external_registry" not in first_manager.dump()
    finally:
        first_manager.close()
        second_manager.close()


def test_plugin_manager_keeps_scheduling_startup_source_refresh_until_one_runs(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    source = PluginSource(
        source_id="test-source",
        display_name="Test Source",
        manifest_url="https://example.invalid/source.toml",
        pinned_source_public_key="key",
        auth_config=PluginSourceAuthConfig(),
        enabled=True,
        last_seen_source_serial=1,
    )
    loop_in_thread = _ImmediateLoopInThread()

    monkeypatch.setattr(ExternalPluginRegistry, "load_sources", lambda self: [source])
    first_manager = PluginManager(
        **_plugin_manager_init_kwargs(tmp_path, loop_in_thread=loop_in_thread),
        parent=None,
    )
    second_manager = PluginManager(
        **_plugin_manager_init_kwargs(tmp_path, loop_in_thread=loop_in_thread),
        parent=None,
    )

    try:
        assert first_manager._startup_source_refresh_timer is not None
        assert second_manager._startup_source_refresh_timer is not None
        assert first_manager.external_registry.last_download_time is None
        assert second_manager.external_registry.last_download_time is None
    finally:
        first_manager.close()
        second_manager.close()


def test_plugin_manager_skips_startup_source_refresh_when_last_download_is_recent(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    source = PluginSource(
        source_id="test-source",
        display_name="Test Source",
        manifest_url="https://example.invalid/source.toml",
        pinned_source_public_key="key",
        auth_config=PluginSourceAuthConfig(),
        enabled=True,
        last_seen_source_serial=1,
    )
    config = _make_config(tmp_path)
    external_registry = ExternalPluginRegistry(config)
    external_registry.last_download_time = datetime.now(timezone.utc)
    external_registry.save()

    monkeypatch.setattr(ExternalPluginRegistry, "load_sources", lambda self: [source])
    manager = PluginManager(
        wallet_functions=WalletFunctions(Signals()),
        config=config,
        fx=_DummyFX(),
        loop_in_thread=_ImmediateLoopInThread(),
        external_registry=external_registry,
        parent=None,
    )

    try:
        assert manager._startup_source_refresh_timer is None
    finally:
        manager.close()


def test_plugin_manager_reschedules_startup_source_refresh_after_restart(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    source = PluginSource(
        source_id="test-source",
        display_name="Test Source",
        manifest_url="https://example.invalid/source.toml",
        pinned_source_public_key="key",
        auth_config=PluginSourceAuthConfig(),
        enabled=True,
        last_seen_source_serial=1,
    )
    loop_in_thread = _ImmediateLoopInThread()
    refresh_calls: list[bool] = []

    monkeypatch.setattr(ExternalPluginRegistry, "load_sources", lambda self: [source])
    monkeypatch.setattr(
        PluginManager,
        "refresh_plugin_sources",
        lambda self, source_id=None, show_errors=True: _mark_source_refresh_run(
            self, refresh_calls, show_errors
        ),
    )
    first_manager = PluginManager(
        **_plugin_manager_init_kwargs(tmp_path, loop_in_thread=loop_in_thread),
        parent=None,
    )

    try:
        first_manager._refresh_plugin_sources_after_startup()
        second_manager = PluginManager(
            **_plugin_manager_init_kwargs(tmp_path, loop_in_thread=loop_in_thread),
            parent=None,
        )
        try:
            assert refresh_calls == [False]
            assert first_manager.external_registry.last_download_time is not None
            assert second_manager.external_registry.last_download_time is None
            assert second_manager._startup_source_refresh_timer is not None
        finally:
            second_manager.close()
    finally:
        first_manager.close()


def test_plugin_manager_from_dump_reuses_external_state_from_class_kwargs(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    refresh_calls = 0

    def _counting_refresh(cls, context, external_registry):
        del cls, context, external_registry
        nonlocal refresh_calls
        refresh_calls += 1
        return {}

    monkeypatch.setattr(PluginManager, "_refresh_external_state", classmethod(_counting_refresh))

    signals = Signals()
    wallet_functions = WalletFunctions(signals)
    config = _make_config(tmp_path)
    class_kwargs = PluginManager.class_kwargs(
        wallet_functions=wallet_functions,
        config=config,
        fx=_DummyFX(),
        loop_in_thread=None,
        parent=None,
        external_registry=ExternalPluginRegistry(config),
    )

    manager = PluginManager.from_dump(
        {
            "__class__": PluginManager.__name__,
            "VERSION": PluginManager.VERSION,
            "clients": [],
            "plugin_permissions": {},
        },
        class_kwargs=class_kwargs,
    )

    try:
        assert refresh_calls == 1
    finally:
        manager.close()


def test_plugin_manager_dump_writes_serialized_client_dumps_for_legacy_client_state(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    _patch_plugin_manager_for_builtin_client(
        monkeypatch, _DisplayMetadataPluginClient, _GenericBuiltinBundleModule
    )

    client = _DisplayMetadataPluginClient()
    client.set_plugin_identity(plugin_source=PluginClientSource.BUILTIN)
    manager = PluginManager.from_dump(
        {
            "__class__": PluginManager.__name__,
            "VERSION": "0.0.16",
            "clients": [client],
            "plugin_permissions": {},
        },
        class_kwargs=_plugin_manager_class_kwargs(tmp_path),
    )

    try:
        dumped = manager.dump()

        assert "serialized_client_dumps" in dumped
        assert len(dumped["serialized_client_dumps"]) == 1
        assert "clients" not in dumped
        assert manager.serialized_client_dumps == []
        assert manager.clients == [client]
    finally:
        manager.close()


def test_plugin_manager_from_dump_keeps_legacy_deserialized_clients(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    _patch_plugin_manager_for_builtin_client(
        monkeypatch, _CloseTrackingPluginClient, _GenericBuiltinBundleModule
    )

    client = _CloseTrackingPluginClient()
    client.set_plugin_identity(plugin_source=PluginClientSource.BUILTIN)
    manager = PluginManager.from_dump(
        {
            "__class__": PluginManager.__name__,
            "VERSION": "0.0.16",
            "clients": [client],
            "plugin_permissions": {},
        },
        class_kwargs=_plugin_manager_class_kwargs(tmp_path),
    )

    try:
        assert client.close_calls == 0
        assert manager.clients == [client]
        assert manager.serialized_client_dumps == []
    finally:
        manager.close()


def test_plugin_manager_from_dump_defers_restore_of_known_serialized_client_payload(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    _patch_plugin_manager_for_builtin_client(
        monkeypatch, _DisplayMetadataPluginClient, _GenericBuiltinBundleModule
    )

    client = _DisplayMetadataPluginClient()
    client.set_plugin_identity(plugin_source=PluginClientSource.BUILTIN)
    payload = _serialized_client_payload(client)
    client.close()

    manager = PluginManager.from_dump(
        {
            "__class__": PluginManager.__name__,
            "VERSION": PluginManager.VERSION,
            "serialized_client_dumps": [payload],
            "plugin_permissions": {},
        },
        class_kwargs=_plugin_manager_class_kwargs(tmp_path),
    )

    try:
        assert manager.clients == []
        assert manager.serialized_client_dumps == [payload]
    finally:
        manager.close()


def test_plugin_manager_from_dump_preserves_unknown_serialized_client_payload(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    monkeypatch.setattr(
        PluginManager,
        "_refresh_external_state",
        classmethod(lambda cls, context, external_registry: {}),
    )
    payload = BaseSaveableClass.dumps_object(
        {
            "__class__": "MissingPluginClient",
            "VERSION": "0.0.1",
            "plugin_id": "missing-plugin",
            "plugin_source": PluginClientSource.EXTERNAL.value,
            "plugin_bundle_id": "missing-plugin",
            "enabled": False,
        }
    )

    manager = PluginManager.from_dump(
        {
            "__class__": PluginManager.__name__,
            "VERSION": PluginManager.VERSION,
            "serialized_client_dumps": [payload],
            "plugin_permissions": {},
        },
        class_kwargs=_plugin_manager_class_kwargs(tmp_path),
    )

    try:
        assert manager.clients == []
        assert manager.serialized_client_dumps == [payload]
    finally:
        manager.close()


def test_plugin_manager_restores_pending_serialized_client_when_class_becomes_available(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    client = _DisplayMetadataPluginClient()
    client.set_plugin_identity(plugin_source=PluginClientSource.BUILTIN)
    payload = _serialized_client_payload(client)
    client.close()

    monkeypatch.setattr(
        PluginManager,
        "_refresh_external_state",
        classmethod(lambda cls, context, external_registry: {}),
    )
    manager = PluginManager.from_dump(
        {
            "__class__": PluginManager.__name__,
            "VERSION": PluginManager.VERSION,
            "serialized_client_dumps": [payload],
            "plugin_permissions": {},
        },
        class_kwargs=_plugin_manager_class_kwargs(tmp_path),
    )

    _patch_plugin_manager_for_builtin_client(
        monkeypatch, _DisplayMetadataPluginClient, _GenericBuiltinBundleModule
    )

    try:
        manager.create_and_connect_clients(
            descriptor=_test_descriptor(),
            wallet_id="wallet-id",
            category_core=SimpleNamespace(),
        )

        assert len(manager.clients) == 1
        assert isinstance(manager.clients[0], _DisplayMetadataPluginClient)
        assert manager.serialized_client_dumps == []
    finally:
        manager.close()


def test_plugin_manager_keeps_payload_pending_when_client_from_dump_fails_then_restores_later(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp
    client = _FailingFromDumpPluginClient()
    client.set_plugin_identity(plugin_source=PluginClientSource.BUILTIN)
    payload = _serialized_client_payload(client)
    client.close()

    _patch_plugin_manager_for_builtin_client(
        monkeypatch, _FailingFromDumpPluginClient, _FailingBuiltinBundleModule
    )
    manager = PluginManager.from_dump(
        {
            "__class__": PluginManager.__name__,
            "VERSION": PluginManager.VERSION,
            "serialized_client_dumps": [payload],
            "plugin_permissions": {},
        },
        class_kwargs=_plugin_manager_class_kwargs(tmp_path),
    )

    try:
        assert manager.clients == []
        assert manager.serialized_client_dumps == [payload]

        _FailingFromDumpPluginClient.should_fail = False

        manager.create_and_connect_clients(
            descriptor=_test_descriptor(),
            wallet_id="wallet-id",
            category_core=SimpleNamespace(),
        )

        assert len(manager.clients) == 1
        assert isinstance(manager.clients[0], _FailingFromDumpPluginClient)
        assert manager.serialized_client_dumps == []
    finally:
        _FailingFromDumpPluginClient.should_fail = True
        manager.close()


def test_delete_installed_source_plugin_keeps_serialized_payload_and_clears_permissions(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    del qapp

    monkeypatch.setattr(
        PluginManager,
        "_refresh_external_state",
        classmethod(lambda cls, context, external_registry: {}),
    )
    monkeypatch.setattr("bitcoin_safe.plugin_framework.plugin_manager.question_dialog", lambda **kwargs: True)

    client = _DisplayMetadataPluginClient()
    client.set_plugin_identity(
        plugin_source=PluginClientSource.EXTERNAL,
        plugin_bundle_id="test-plugin",
    )
    client.set_enabled(False)
    manager = PluginManager(
        clients=[client],
        plugin_permissions={client.plugin_id: {PluginPermission.LABELS}},
        parent=None,
        **_plugin_manager_init_kwargs(tmp_path),
    )
    assert client.plugin_source == PluginClientSource.EXTERNAL
    assert client.plugin_bundle_id == "test-plugin"

    removed_bundle_ids: list[str] = []

    try:
        monkeypatch.setattr(
            manager.external_registry,
            "remove_installed_plugin",
            lambda bundle_id: removed_bundle_ids.append(bundle_id),
        )
        monkeypatch.setattr(manager, "_refresh_external_registry_state", lambda: False)
        monkeypatch.setattr(manager, "_refresh_after_registry_change", lambda runtime_changed: None)

        manager.delete_installed_source_plugin(client)

        assert removed_bundle_ids == ["test-plugin"]
        assert manager.clients == []
        assert client.plugin_id not in manager.plugin_permissions
        assert len(manager.serialized_client_dumps) == 1
        assert PluginManager._payload_identity(manager.serialized_client_dumps[0]) == client.plugin_id
    finally:
        manager.close()


def test_plugin_manager_widget_sidebar_rebuild_keeps_other_enabled_plugins_visible(
    qapp: QApplication,
) -> None:
    del qapp
    widget = PluginManagerWidget(parent=None)
    plugin_a = _DisplayMetadataPluginClient()
    plugin_b = _DisplayMetadataPluginClient()
    replacement_a = _DisplayMetadataPluginClient()
    replacement_a.set_enabled(False)

    try:
        widget.set_plugins([plugin_a, plugin_b])

        assert not plugin_a.node.isHidden()
        assert not plugin_b.node.isHidden()

        widget.set_plugins([replacement_a, plugin_b])
        replacement_a.set_enabled(True)

        assert not replacement_a.node.isHidden()
        assert not plugin_b.node.isHidden()
    finally:
        widget.close()
        plugin_a.close()
        plugin_b.close()
        replacement_a.close()


def test_sidebar_node_remove_child_preserves_subtree(qapp: QApplication) -> None:
    del qapp
    root = SidebarNode(data="root", title="Root")
    stack = QStackedWidget()
    root._attach_to_stack(stack)

    plugin_widget = QWidget()
    plugin_node = SidebarNode(data="plugin", widget=plugin_widget, title="Plugin")
    payouts_node = SidebarNode(data="payouts", widget=QWidget(), title="Payouts")
    recipients_node = SidebarNode(data="recipients", widget=QWidget(), title="Recipients")
    plugin_node.addChildNode(payouts_node, focus=False)
    plugin_node.addChildNode(recipients_node, focus=False)
    root.addChildNode(plugin_node, focus=False)

    assert [child.title for child in plugin_node.child_nodes] == ["Payouts", "Recipients"]
    assert plugin_node.findNodeByTitle("Payouts") is payouts_node
    assert plugin_node.findNodeByTitle("Recipients") is recipients_node
    assert not plugin_node.isHidden()

    root.removeChildNode(plugin_node)

    assert [child.title for child in plugin_node.child_nodes] == ["Payouts", "Recipients"]
    assert plugin_node.findNodeByTitle("Payouts") is payouts_node
    assert plugin_node.findNodeByTitle("Recipients") is recipients_node
    assert plugin_node.parent_node is None
    assert plugin_node.stack is None
    assert payouts_node.stack is None
    assert recipients_node.stack is None

    root.addChildNode(plugin_node, focus=False)

    assert plugin_node.parent_node is root
    assert plugin_node.stack is stack
    assert payouts_node.stack is stack
    assert recipients_node.stack is stack
    assert not plugin_node.isHidden()


def test_sidebar_tree_close_skips_unreachable_history_node(qapp: QApplication) -> None:
    del qapp
    host = QWidget()
    layout = QVBoxLayout(host)
    tree = SidebarTree[str]()
    layout.addWidget(tree)
    host.show()
    QApplication.processEvents()

    group_hidden = SidebarNode(data="group-hidden", title="Group hidden")
    hidden_leaf = SidebarNode(data="hidden-leaf", title="Hidden leaf", widget=QWidget())
    group_hidden.addChildNode(hidden_leaf, focus=False)

    group_visible = SidebarNode(data="group-visible", title="Group visible")
    closing_leaf = SidebarNode(data="closing-leaf", title="Closing leaf", widget=QWidget())
    fallback_leaf = SidebarNode(data="fallback-leaf", title="Fallback leaf", widget=QWidget())
    group_visible.addChildNode(closing_leaf, focus=False)
    group_visible.addChildNode(fallback_leaf, focus=False)

    tree.root.addChildNode(group_hidden, focus=False)
    tree.root.addChildNode(group_visible, focus=False)

    hidden_leaf.select()
    group_hidden.set_collapsed(True)
    closing_leaf.select()

    assert not hidden_leaf._is_reachable_in_sidebar()

    closing_leaf.removeNode()
    QApplication.processEvents()

    assert tree.currentNode() is fallback_leaf


def test_sidebar_tree_close_top_level_tab_skips_hidden_wizard_widget(qapp: QApplication) -> None:
    del qapp
    host = QWidget()
    layout = QVBoxLayout(host)
    tree = SidebarTree[str]()
    layout.addWidget(tree)
    host.show()
    QApplication.processEvents()

    wallet = SidebarNode(data="wallet", title="Wallet")
    history_leaf = SidebarNode(data="history", title="History", widget=QWidget())
    wizard_leaf = SidebarNode(data="wizard", title="Wizard", widget=QWidget())
    wallet.addChildNode(history_leaf, focus=False)
    wallet.addChildNode(wizard_leaf, focus=False)

    tx_leaf = SidebarNode(data="tx", title="Tx", widget=QWidget(), closable=True)

    tree.root.addChildNode(wallet, focus=False)
    tree.root.addChildNode(tx_leaf, focus=False)

    history_leaf.select()
    wizard_leaf.setVisible(False)
    tx_leaf.select()
    QApplication.processEvents()

    tx_leaf.removeNode()
    QApplication.processEvents()

    assert tree.currentNode() is history_leaf
    assert tree.currentWidget() is history_leaf.widget


def test_sidebar_node_trailing_buttons_are_parented_before_insertion(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    del qapp
    original_add_square_button = SidebarRow.add_square_button
    parent_widgets: list[QWidget | None] = []

    def add_square_button(self: SidebarRow, btn: QWidget) -> None:
        parent_widgets.append(btn.parentWidget())
        original_add_square_button(self, btn)

    monkeypatch.setattr(SidebarRow, "add_square_button", add_square_button)

    node = SidebarNode(data="wallet", title="Wallet", closable=True, hidable=True, show_expand_button=True)
    node.addChildNode(SidebarNode(data="history", title="History", widget=QWidget()), focus=False)

    assert parent_widgets
    assert all(parent is node.header_row for parent in parent_widgets)
