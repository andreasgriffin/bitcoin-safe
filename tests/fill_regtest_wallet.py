#
# Bitcoin Safe
# Copyright (C) 2024 Andreas Griffin
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


import argparse
import json
import time
from random import randint
from typing import List, Optional, Union

import bdkpython as bdk
import numpy as np
import requests


class ProgressPrint:
    def update(self, progress: "float", message: "Optional[str]"):
        print(str((progress, message)))


def send_rpc_command(ip: str, port: Union[str, int], username: str, password: str, method: str, params=None):
    """Sends an RPC command to a Bitcoin node.

    :param ip: IP address of the Bitcoin node.
    :param port: RPC port of the Bitcoin node.
    :param username: RPC username.
    :param password: RPC password.
    :param method: RPC method/command to execute.
    :param params: Parameters for the RPC method (default: empty list).
    :return: The response of the RPC command.
    """
    if not params:
        params = []

    # Create the URL for the RPC endpoint
    url = f"http://{ip}:{port}"

    # Create the headers
    headers = {"content-type": "application/json"}

    # Create the payload with the RPC command and parameters
    payload = json.dumps(
        {
            "method": method,
            "params": params,
            "id": "1",  # This can be any ID, used for identifying the request
        }
    )

    # Send the request and get the response
    response = requests.post(url, headers=headers, data=payload, auth=(username, password), timeout=20)

    # Return the response
    return response.json()


def mine_coins(rpc_ip, rpc_username, rpc_password, wallet, blocks=101, always_new_addresses=False):
    """Mine some blocks to generate coins for the wallet."""
    address = wallet.get_address(
        bdk.AddressIndex.NEW() if always_new_addresses else bdk.AddressIndex.LAST_UNUSED()
    ).address.as_string()
    print(f"Mining {blocks} blocks to {address}")
    ip, port = rpc_ip.split(":")
    response = send_rpc_command(
        ip,
        port,
        rpc_username,
        rpc_password,
        "generatetoaddress",
        params=[blocks, address],
    )
    print(response)


def extend_tip(wallet, n):
    return [wallet.get_address(bdk.AddressIndex.NEW()) for i in range(n)]


def generate_random_own_addresses_info(wallet: bdk.Wallet, n=10, always_new_addresses=False):
    if always_new_addresses:
        address_indices = [wallet.get_address(bdk.AddressIndex.NEW()).index for _ in range(n)]
    else:
        tip = wallet.get_address(bdk.AddressIndex.LAST_UNUSED()).index
        address_indices = [np.random.choice(np.arange(tip)) for _ in range(n)]

    address_infos = []
    for i in address_indices:
        address_info: bdk.AddressInfo = wallet.get_address(bdk.AddressIndex.PEEK(i))
        # print(f"Generating address {address_info.index}")
        address_infos.append(address_info)
    return address_infos


# Function to create complex transactions
def create_complex_transactions(
    rpc_ip, rpc_username, rpc_password, wallet: bdk.Wallet, blockchain, n=300, always_new_addresses=True
):
    for i in range(n):
        try:
            # Build the transaction
            tx_builder = bdk.TxBuilder().fee_rate(1.0).enable_rbf()

            recieve_address_infos: List[bdk.AddressInfo] = generate_random_own_addresses_info(
                wallet, randint(1, 10), always_new_addresses=always_new_addresses
            )
            for recieve_address_info in recieve_address_infos:
                amount = randint(10000, 1000000)  # Random amount
                tx_builder = tx_builder.add_recipient(recieve_address_info.address.script_pubkey(), amount)

            # Finish and sign transaction
            tx_final = tx_builder.finish(wallet)
            psbt2 = bdk.PartiallySignedTransaction(tx_final.psbt.serialize())
            wallet.sign(psbt2, None)
            final_tx = psbt2.extract_tx()

            # Broadcast the transaction
            blockchain.broadcast(final_tx)

            print(
                f"Broadcast tx {final_tx.txid()} to addresses {[recieve_address_info.index for recieve_address_info in recieve_address_infos]}"
            )
            if np.random.random() < 0.2:
                mine_coins(
                    rpc_ip,
                    rpc_username,
                    rpc_password,
                    wallet,
                    blocks=1,
                    always_new_addresses=always_new_addresses,
                )

            wallet.sync(blockchain, None)
        except Exception:
            # print(e)
            pass


# Synchronize the wallet
def update(progress: float, message: str):
    print(progress, message)


def main():

    # Initialize bdk and configurations
    network = bdk.Network.REGTEST

    # Set up argument parsing
    parser = argparse.ArgumentParser(description="Bitcoin Wallet Operations")
    parser.add_argument("-s", "--seed", help="Mnemonic seed phrase", type=str, default="")
    parser.add_argument("-d", "--descriptor", help="Descriptor", type=str, default="")
    parser.add_argument("-m", "--mine", type=int, default=0)
    parser.add_argument("-tx", "--transactions", type=int, default=20)
    parser.add_argument("--always_new_addresses", action="store_true")
    args = parser.parse_args()

    db_config = bdk.DatabaseConfig.MEMORY()

    gap = 20

    rpc_ip = "127.0.0.1:18443"
    rpc_username = "admin1"
    rpc_password = "123"
    # RPC Blockchain Configuration
    blockchain_config = bdk.BlockchainConfig.RPC(
        bdk.RpcConfig(
            url=rpc_ip,
            auth=bdk.Auth.USER_PASS(username=rpc_username, password=rpc_password),
            network=network,
            wallet_name="new0-51117772c02f89651e192a79b2deac8d332cc1a5b67bb21e931d2395e5455c1a9b7c",
            sync_params=bdk.RpcSyncParams(
                start_script_count=0, start_time=0, force_start_time=False, poll_rate_sec=10
            ),
        )
    )
    blockchain_config = bdk.BlockchainConfig.ESPLORA(
        bdk.EsploraConfig(
            base_url="http://127.0.0.1:3000", proxy=None, concurrency=1, stop_gap=gap * 2, timeout=20
        )
    )

    blockchain = bdk.Blockchain(config=blockchain_config)

    # Create Wallet
    if args.descriptor:
        descriptor = bdk.Descriptor(args.descriptor, network)
        wallet = bdk.Wallet(
            descriptor=descriptor,
            change_descriptor=None,
            network=network,
            database_config=db_config,
        )

    if args.seed:

        # Use provided mnemonic or generate a new one
        mnemonic = bdk.Mnemonic.from_string(args.seed) if args.seed else None
        if mnemonic:
            print(f"Mnemonic: {mnemonic.as_string()}")
        descriptor = bdk.Descriptor.new_bip84(
            secret_key=bdk.DescriptorSecretKey(network, mnemonic, ""),
            keychain=bdk.KeychainKind.EXTERNAL,
            network=network,
        )
        change_descriptor = bdk.Descriptor.new_bip84(
            secret_key=bdk.DescriptorSecretKey(network, mnemonic, ""),
            keychain=bdk.KeychainKind.INTERNAL,
            network=network,
        )
        wallet = bdk.Wallet(
            descriptor=descriptor,
            change_descriptor=change_descriptor,
            network=network,
            database_config=db_config,
        )

    if not wallet:
        raise Exception("A wallet cannot be defined")

    # Mine some blocks to get coins
    mine_coins(
        rpc_ip,
        rpc_username,
        rpc_password,
        wallet,
        blocks=args.mine,
        always_new_addresses=args.always_new_addresses,
    )
    if args.mine:
        time.sleep(5)

    # Synchronize the wallet
    wallet.sync(blockchain, progress=ProgressPrint())

    print(wallet.get_balance())

    #  create transactions
    extend_tip(wallet, gap // 5)
    create_complex_transactions(
        rpc_ip,
        rpc_username,
        rpc_password,
        wallet,
        blockchain,
        n=args.transactions,
        always_new_addresses=args.always_new_addresses,
    )


if __name__ == "__main__":
    main()
