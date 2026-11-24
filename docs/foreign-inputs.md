# Importing transaction inputs and PSBTs

Use **Import UTXOs from wallet** to take a one-time snapshot of another loaded
wallet's currently spendable outputs. Imported inputs are not selected automatically.
Import the wallet again to include outputs it receives later. Closing the originating
wallet does not remove imported inputs; remove individual inputs from the UTXO list.

Every imported foreign input requires its complete previous transaction, including
Taproot inputs. Bitcoin Safe checks its transaction ID, output index, amount and script
against the supplied PSBT and locally known wallet data. When the transaction is not
available locally, an explicit import may download it from the configured block
explorer. The explorer can see the requested transaction IDs. Wallet updates and draft
restoration do not initiate downloads. A failed import can be retried manually.

P2WPKH inputs can be imported without a loaded owning wallet. Other input types need
sufficient validated PSBT metadata and a matching loaded, synchronized wallet to
determine scripts and satisfaction weight. Imported signatures and sighash policies
are discarded because the transaction is reconstructed.

Imported inputs are saved with the draft, even when not selected. Inputs known to be
spent by a loaded wallet cannot be used. An unavailable selected input remains visible
and blocks transaction creation until it is deselected or made available again.

Merging a PSBT imports all of its inputs and outputs together. Outputs without an
address, such as OP_RETURN, are shown as `script:` followed by the hexadecimal script
and retain their original amount. Review the outputs before creating a transaction.
