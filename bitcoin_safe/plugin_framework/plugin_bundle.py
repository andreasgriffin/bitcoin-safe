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

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import bdkpython as bdk
from bitcoin_safe_lib.async_tools.loop_in_thread import LoopInThread
from PyQt6.QtWidgets import QWidget

from bitcoin_safe.config import UserConfig
from bitcoin_safe.fx import FX
from bitcoin_safe.plugin_framework.plugin_client import PluginClient
from bitcoin_safe.plugin_framework.subscription_price_lookup import SubscriptionPriceLookup
from bitcoin_safe.signals import WalletFunctions

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginRuntimeContext:
    wallet_functions: WalletFunctions
    config: UserConfig
    fx: FX
    loop_in_thread: LoopInThread | None
    subscription_price_lookup: SubscriptionPriceLookup | None
    parent: QWidget | None


class PluginBundleModule(Protocol):
    PLUGIN_CLIENTS: tuple[type[PluginClient], ...]

    def class_kwargs(self, context: PluginRuntimeContext) -> dict[str, dict[str, object]]: ...


class FactoryPluginBundleModule(PluginBundleModule, Protocol):
    def create_plugin_clients(
        self,
        context: PluginRuntimeContext,
        descriptor: bdk.Descriptor,
    ) -> tuple[PluginClient, ...]: ...


class StaticAutoAllowPluginBundleModule(PluginBundleModule, Protocol):
    AUTO_ALLOW_PLUGIN_CLIENTS: tuple[type[PluginClient], ...]


@dataclass(frozen=True)
class RuntimePluginBundle:
    client_classes: tuple[type[PluginClient], ...]
    class_kwargs: dict[str, dict[str, object]]
    create_plugin_clients: Callable[[PluginRuntimeContext, bdk.Descriptor], tuple[PluginClient, ...]] | None
    auto_allow_plugin_clients: tuple[type[PluginClient], ...]


@dataclass(frozen=True)
class StaticPluginBundleRegistration:
    module: PluginBundleModule
    auto_allow_plugin_clients: tuple[type[PluginClient], ...]


def ensure_plugin_import_path(path: Path) -> None:
    resolved_path = str(path.resolve(strict=False))
    if resolved_path not in sys.path:
        sys.path.insert(0, resolved_path)


def register_static_plugin_bundle(
    module: PluginBundleModule,
) -> StaticPluginBundleRegistration:
    auto_allow_plugin_clients = getattr(
        module,
        "AUTO_ALLOW_PLUGIN_CLIENTS",
        module.PLUGIN_CLIENTS,
    )

    return StaticPluginBundleRegistration(
        module=module,
        auto_allow_plugin_clients=auto_allow_plugin_clients,
    )


def plugin_bundle_client_classes(
    module: PluginBundleModule,
    *,
    error_type: type[Exception] = ValueError,
    bundle_name: str = "plugin bundle",
) -> tuple[type[PluginClient], ...]:
    exported_clients = module.PLUGIN_CLIENTS
    if not isinstance(exported_clients, tuple) or not exported_clients:
        raise error_type(f"{bundle_name} must export PLUGIN_CLIENTS.")

    client_classes: list[type[PluginClient]] = []
    for client_cls in exported_clients:
        if not isinstance(client_cls, type) or not issubclass(client_cls, PluginClient):
            raise error_type(f"{bundle_name} exports a non-PluginClient.")
        client_classes.append(client_cls)

    return tuple(client_classes)


def normalize_runtime_plugin_bundle(
    module: PluginBundleModule,
    context: PluginRuntimeContext,
    *,
    auto_allow_plugin_clients: tuple[type[PluginClient], ...] = (),
    bundle_name: str = "plugin bundle",
    error_type: type[Exception] = ValueError,
    additional_class_kwargs_by_client_class: dict[type[PluginClient], dict[str, object]] | None = None,
) -> RuntimePluginBundle:
    module_dict = cast(dict[str, object], module.__dict__)
    client_classes = plugin_bundle_client_classes(
        module,
        error_type=error_type,
        bundle_name=bundle_name,
    )

    class_kwargs_factory = module.class_kwargs
    if not callable(class_kwargs_factory):
        raise error_type(f"{bundle_name} must export class_kwargs(context).")

    raw_class_kwargs = class_kwargs_factory(context)
    if not isinstance(raw_class_kwargs, dict):
        raise error_type(f"{bundle_name} returned invalid class kwargs.")

    class_kwargs: dict[str, dict[str, object]] = {}
    for client_cls in client_classes:
        entry = raw_class_kwargs.get(client_cls.__name__)
        if not isinstance(entry, dict):
            raise error_type(f"{bundle_name} does not define class kwargs for {client_cls.__name__}.")
        class_kwargs[client_cls.__name__] = dict(entry)
        if additional_class_kwargs_by_client_class and client_cls in additional_class_kwargs_by_client_class:
            class_kwargs[client_cls.__name__].update(additional_class_kwargs_by_client_class[client_cls])

    raw_create_plugin_clients = module_dict.get("create_plugin_clients")
    if raw_create_plugin_clients is not None and not callable(raw_create_plugin_clients):
        raise error_type(f"{bundle_name} exports an invalid create_plugin_clients(context, descriptor).")

    create_plugin_clients = (
        cast(
            Callable[[PluginRuntimeContext, bdk.Descriptor], tuple[PluginClient, ...]],
            raw_create_plugin_clients,
        )
        if raw_create_plugin_clients is not None
        else None
    )

    return RuntimePluginBundle(
        client_classes=client_classes,
        class_kwargs=class_kwargs,
        create_plugin_clients=create_plugin_clients,
        auto_allow_plugin_clients=auto_allow_plugin_clients,
    )


def normalize_static_plugin_bundle(
    bundle: StaticPluginBundleRegistration,
    context: PluginRuntimeContext,
) -> RuntimePluginBundle:
    return normalize_runtime_plugin_bundle(
        module=bundle.module,
        context=context,
        auto_allow_plugin_clients=bundle.auto_allow_plugin_clients,
    )


def create_runtime_plugin_clients(
    bundle: RuntimePluginBundle,
    context: PluginRuntimeContext,
    descriptor: bdk.Descriptor,
    *,
    initial_dumps_by_client_class: dict[type[PluginClient], dict[str, object]] | None = None,
    bundle_name: str = "plugin bundle",
    error_type: type[Exception] = ValueError,
) -> tuple[PluginClient, ...]:
    if bundle.create_plugin_clients is not None:
        try:
            created_clients = bundle.create_plugin_clients(context, descriptor)
            if not isinstance(created_clients, tuple):
                raise error_type(f"{bundle_name} returned invalid plugin instances.")
            for client in created_clients:
                if not isinstance(client, PluginClient) or client.__class__ not in bundle.client_classes:
                    raise error_type(
                        f"{bundle_name} returned a client that is not declared in PLUGIN_CLIENTS."
                    )
            return created_clients
        except Exception as exc:
            logger.error("Could not create plugin clients from %s due to %s", bundle_name, exc)
            logger.debug("Failed plugin bundle factory", exc_info=True)
            return ()

    constructed_clients: list[PluginClient] = []
    for client_cls in bundle.client_classes:
        client_dump = {
            "__class__": client_cls.__name__,
            "VERSION": client_cls.VERSION,
            "enabled": False,
        }
        if initial_dumps_by_client_class and client_cls in initial_dumps_by_client_class:
            client_dump.update(initial_dumps_by_client_class[client_cls])
        try:
            constructed_clients.append(
                client_cls.from_dump(
                    client_dump,
                    class_kwargs=bundle.class_kwargs[client_cls.__name__],
                )
            )
        except Exception as exc:
            logger.error(
                "Could not restore %s from %s due to %s",
                client_cls.__name__,
                bundle_name,
                exc,
            )
            logger.debug("Failed client restore", exc_info=True)
    return tuple(constructed_clients)
