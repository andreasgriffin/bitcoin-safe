import bdkpython as bdk
import pytest

from bitcoin_safe.config import UserConfig
from bitcoin_safe.storage import Storage
from bitcoin_safe.util import rel_home_path_to_abs_path
from bitcoin_safe.wallet import Wallet


@pytest.fixture
def config() -> UserConfig:
    config = UserConfig()
    config.network = bdk.Network.REGTEST

    return config


def test_011(config: UserConfig):
    file_path = "tests/data/0.1.1.wallet"

    password = None

    assert not Storage().has_password(file_path)

    wallet = Wallet.from_file(file_path, config, password)

    assert wallet


def test_config010(config: UserConfig):
    file_path = "tests/data/config_0.1.0.conf"

    config = UserConfig.from_file(file_path=file_path)
    assert config.last_wallet_files == {"Network.REGTEST": [".config/bitcoin_safe/REGTEST/Coldcard.wallet"]}
    assert config.data_dir == rel_home_path_to_abs_path(".local/share/bitcoin_safe")

    assert config
