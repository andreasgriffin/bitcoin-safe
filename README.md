# Bitcoin Safe

#### A bitcoin savings wallet for the entire family

- **Easy** Multisig-Wallet Setup
  - Step-by-Step instructions for a secure MultiSig setup with PDF backup sheets
  - Test transactions ensure that all hardware signers are ready
  - Full support for [Coldcard](https://store.coinkite.com/promo/8BFF877000C34A86F410), [Coldcard Q](https://store.coinkite.com/promo/8BFF877000C34A86F410), [Bitbox02](https://shiftcrypto.ch/bitbox02/?ref=MOB4dk7gpm), [Blockstream Jade](https://store.blockstream.com/?code=XEocg5boS77D), [Trezor](https://trezor.io), [Foundation Passport](https://foundation.xyz/passport), [Keystone](https://keyst.one), [Ledger](https://shop.ledger.com/pages/ledger-nano-s-plus), [Specter DIY](https://specter.solutions/hardware), using  *QR*, *USB*, and *SD-card* 
- **Secure**: Hardware signers only
  - All wallets require hardware signers/wallets for safe seed storage 
  - Powered by **[BDK](https://github.com/bitcoindevkit/bdk)**
- **Multi-Language**:
  - 🇺🇸 English, 🇨🇳 Chinese - 简体中文, 🇪🇸 Spanish - español de España, 🇯🇵 Japanese - 日本語, 🇷🇺 Russian - русский, 🇵🇹 Portuguese - português europeu, 🇮🇳 Hindi - हिन्दी, Arabic - العربية, 🇮🇹 Italian - italiano, 🇫🇷 French - Français, 🇩🇪 German - Deutsch, (more upon request)
- **Simpler** address labels by using categories (e.g. "KYC", "Non-KYC", "Work", "Friends", ...)
  - Automatic coin selection within categories
  - Transaction flow diagrams, visualizing inputs and outputs, click on inputs and output to trace the money flow
- **Sending** for non-technical users
  - 1-click fee selection via mempool-blocks
  - Automatic merging of utxos when fees are low
- **Sync & Chat**:
  - Encrypted cloud backup (via nostr) of labels
  - Label synchronization between different computers
  - Wallet chat and PSBTs sharing between different computers
- **Fast**: 
  - Electrum server syncing
  - planned upgrade to **Compact Block Filters** for the Bitcoin Safe 2.0 release




### Fully featured - Easy and Powerful

| **Multisig setup wizard**          | **Create a PSBT, sign and broadcast**                     |
|--------------------------------|----------------------------|
| ![](docs/multisig-setup.gif) |  ![](docs/send.gif) |
| **Transaction exploring via a diagram**          | **Type-to-search in all wallets**                    |
| ![](docs/explorer.gif) |  ![](docs/global-search.gif) |
|   **Automatic Label Synchronization**      | **Multiparty Multisig collaboration**                  |
| ![](docs/label-sync.gif)  |   ![](docs/psbt-share.gif) |
|   **Coin Categories**      |                 |
| ![](docs/category-drag-and-drop.gif)  |   |



### Available on all platforms
| ![Windows](docs/tx-win.png) | ![Mac OS X](docs/tx-mac.png) | ![Linux](docs/tx-linux.png) |
|-----------------------------|-----------------------------|----------------------------|
| Windows                    | Mac OS X                   | Linux                     |


## Comprehensive Feature List

- **Import and Export Capabilities**
  
  - CSV export for all lists
  - CSV import for batch transactions
  - Label import and export using [BIP329](https://bip329.org/)
  - Label import from Electrum wallet
  - Export of the money flow diagram to svg
  - Drag and drop for Transactions, PSBTs, and CSV files

- **Wallet Features**
  
  - Simplified address labeling using categories like KYC, Non-KYC, Work, Friends
  - Cancel unconfirmed transactions (via Replace-by-Fee)
  - Bump fee on transactions (via Replace-by-Fee)
  - Encrypted wallet storage
  - Backup PDF with Descriptor (Text and QR code)

- **Hardware Signer Connectivity**
  
  - MicroSD (files)
  - USB
  - QR codes (enhanced QR code detection for Laptop cameras)
  - Animated QR codes including [Coldcard/BBQr](https://bbqr.org/) and [UR](https://github.com/BlockchainCommons/Research/blob/master/papers/bcr-2020-005-ur.md) format

- **Search and Filtering Options**
  
  - Fast filtering across txids, utxos, labels, dates, amounts, categories
  - Search across all open wallets, txids, utxos, labels, dates, amounts, categories

- **Languages**
  
  - 🇺🇸 English, 🇨🇳 Chinese - 简体中文, 🇪🇸 Spanish - español de España, 🇯🇵 Japanese - 日本語, 🇷🇺 Russian - русский, 🇵🇹 Portuguese - português europeu, 🇮🇳 Hindi - हिन्दी, Arabic - العربية, 🇮🇹 Italian - italiano, 🇫🇷 French - Français, 🇩🇪 German - Deutsch, (more upon request)

- **Transaction / PSBT Creation**
  
  - 1-click fee selection and mempool block preview
  - Automatic merging of utxos when fees are low
  - Highlighting of own addresses 

- **Security and Reliability**
  
  - No seed generation or storage on mainnet
  - Seed storage requires a separate hardware signer  
  - Update notifications and signature verification
  - Powered by [Bitcoin Development Kit (BDK)](https://github.com/bitcoindevkit/bdk)

- **Ease of Use for Multisig Wallets**
  
  - Simplified setup for multisig wallets, including step-by-step instructions and PDF backup sheet
  - Test signing with all hardware signers
  - Collaborative wallet management including chat and PSBT sharing via nostr and label synchronization between trusted devices
  - Optional custom nostr server 

- **Upcoming Features**
  
  - For the 2.0 Release
    - **Compact Block Filters** by default
      - Compact Block Filters are **fast** and **private**
      - Compact Block Filters (bdk) are being [worked on](https://github.com/bitcoindevkit/bdk/issues/679), and will be included in bdk 1.1. For now RPC, Electrum and Esplora are available, but will be replaced completely with Compact Block Filters.


## Installation from Git repository


### Ubuntu, Debian, Windows

Install dependencies: 

  ```sh
  sudo apt install  qt6-tools-dev-tools libqt6*
  ```

- Install `poetry` and run `bitcoin_safe`
  
  ```sh
  git clone https://github.com/andreasgriffin/bitcoin-safe.git
  cd bitcoin-safe
  pip install poetry  && poetry install && poetry run python -m bitcoin_safe
  ```

### Mac

- Run `bitcoin_safe`
  
  ```sh
  git clone https://github.com/andreasgriffin/bitcoin-safe.git
  cd bitcoin-safe
  python3 -m pip install poetry && python3 -m poetry install && python3 -m poetry run python3 -m bitcoin_safe
  ```

- *Optional*: dependency `zbar`
  
  ```sh
  xcode-select --install
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  brew install zbar 
  ```

## Development

* Run the precommit manually for debugging

```shell
poetry run pre-commit run --all-files
```

#### Regtest docker environement with electrs and mempool

* install docker

```shell
# see https://docs.docker.com/engine/install/ubuntu/
```

* setting up a regtest environment in docker + mempool instance

```shell
curl https://getnigiri.vulpem.com | sudo bash # see https://nigiri.vulpem.com/#install
sudo nigiri start
xdg-open http://localhost:5000/
```

* This creates
  * esplora localhost:3000
    electrs localhost:50000 
  * and a gui block explorer at http://localhost:5000
* Setup mempool instance

```shell
sudo apt install docker-compose
git clone https://github.com/ngutech21/nigiri-mempool.git

pushd nigiri-mempool
sudo docker-compose up -d
sleep 10
# this is needed because the database needs time to start up 
sudo docker-compose up -d
popd
xdg-open http://localhost:8080/

# if the mempool is endlessly loading, then get the debug output with
sudo docker-compose logs -f mempool-api
```

* this opens a mempool at http://localhost:8080/

#### Control the Regtest environment

* get coins to an address

```shell
nigiri rpc generatetoaddress 1 bcrt1qgsnt3d4sny4w4zd5zl9x6jufc5rankqmgphyms9vz0ds73q4xfms655y4c # mine blocks

# or use the internal faucet
nigiri faucet bcrt1qgsnt3d4sny4w4zd5zl9x6jufc5rankqmgphyms9vz0ds73q4xfms655y4c 0.01
```

* ## Installation from PyPi

### Ubuntu, Debian, Windows

- Install `poetry` and run `bitcoin_safe`
  
  ```sh
  pip install bitcoin-safe
  python -m bitcoin_safe
  ```

### Mac

- Run `bitcoin_safe`
  
  ```sh
  python3 -m pip install bitcoin-safe
  python3 -m bitcoin_safe
  ```



## Code signing policy


Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by [SignPath Foundation](https://signpath.org/)


## Privacy policy
This program uses by default
- the electrum/esplora server of [blockstream.com](https://blockstream.com/) to fetch blockchain data
- fetches mempool fee information from [mempool.space](https://mempool.space/)

You can specify your own (personal) server for both in "Network settings".

When enabeling the Sync&Chat feature [default relays](https://github.com/andreasgriffin/bitcoin-nostr-chat/blob/main/bitcoin_nostr_chat/default_relays.py) are used to transmit encrypted data to your approved trusted devices. You can specify your own relay(s) in the Sync&Chat settings.

This program will not transfer any other information to other networked systems unless specifically requested by the user or the person installing or operating it.