# Importing another wallet

Choose **Import from another wallet file** when creating a wallet. Select the source format and file, then choose the account to import. Bitcoin Safe imports public descriptors and supported labels. On test networks, verified BIP39 seeds can also be imported for signing. Mainnet seeds and other private keys are not imported. Test-network seeds can also control mainnet funds, so protect the imported wallet like a recovery backup. Verify the first receive and change addresses with the source wallet before receiving funds.

| Source | Supported input | Password protection |
| --- | --- | --- |
| Electrum | Wallet JSON or BIE1 wallet file | BIE1 is supported; BIE2 requires a device-aware Electrum export |
| Sparrow | Legacy wallet JSON, encrypted legacy wallet, or H2 `.mv.db` / `.db` | Password-protected databases supported |
| Specter Desktop | Wallet JSON; optional address CSV | Not supported |
| Wasabi | KeyManager wallet JSON | No password is needed for public data; no private keys are imported |
| Bitcoin Core | Public `listdescriptors` RPC JSON | Not supported; binary `wallet.dat` is not supported |
| BitBoxApp | Accounts configuration JSON | Not supported |
| Trezor Suite | Supported Bitcoin account JSON | Legacy `.mtdt` labels can be decrypted using the matching Trezor |
| Ledger Live Desktop | Supported Bitcoin account JSON or Desktop `app.json` | Password-locked account data supported |
| Blockstream Green | Compatible Bitcoin singlesig descriptor text or JSON | Login files cannot be imported; 2FA multisig and Liquid accounts are not supported |
| Descriptor | Public receive-and-change multipath descriptor | Not supported |
| Wallet interchange | Exchange JSON, optionally containing test-network BIP39 seeds | Not supported |

Input structures vary by wallet version. If a file does not contain a complete supported receive-and-change descriptor, export a compatible descriptor from the source wallet instead. Some formats do not include a master fingerprint or full signer origin; verify those details with the original device. For formats without embedded labels, optional BIP-329 labels are applied only to the selected account. Formats containing their own labels use the source file instead. Bitcoin Safe warns about labels and metadata it cannot import. Frozen addresses or coins are not protected from spending by this import.

For a modern Sparrow database, close Sparrow or use a consistent backup. The built-in H2 reader needs no Java installation. Some software signers do not have public keys stored in the database. For H2 files, Bitcoin Safe automatically derives public keys from supported BIP39 software seeds, including in unencrypted files. Enter the BIP39 passphrase if the signer uses one. This decrypts the seeds in memory; Python cannot guarantee that sensitive data is erased from memory. Verified test-network BIP39 seeds without a passphrase are imported for signing. Mainnet seeds and seeds using a passphrase are not retained. Verify the first receive and change addresses in Sparrow.

For Trezor legacy labeling, select the `.mtdt` file and enter the original Suite metadata account key, normally the account xpub, along with the labeling encryption version. Connect and unlock the matching Trezor and approve its request. This does not support the newer Suite Sync labeling system.

Electrum signer origins may be missing. Check the genuine master fingerprint on each hardware signer or its original backup and enter it when prompted. The proposed derivation is the standard path for the selected address type and network; verify it against the original signer. An incorrect fingerprint or path can prevent signer identification. The importer checks the path against the account xpub where possible.

Ledger Live Desktop `app.json` uses the application password, not the hardware device PIN or BIP39 passphrase. Only saved account metadata is decrypted. Bitcoin Safe asks for the master fingerprint and account path when the export does not provide them; verify these details with the signer. Compatibility has been tested with synthetic Ledger data, not a real Ledger Live profile.

A Green login file contains no wallet descriptor and cannot be imported. For supported Bitcoin singlesig accounts, copy the output descriptor from Green and save a compatible receive-and-change descriptor in a text file. Green 2FA multisig and Liquid accounts cannot be imported using this flow. See the [Blockstream watch-only instructions](https://help.blockstream.com/blockstream-app/perform-advanced-wallet-operations/set-up-watch-only-wallet).
