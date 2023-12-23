from typing import Dict, List, Tuple
import bdkpython as bdk
import json

from .pythonbdk_types import OutPoint


def parse_witness_script(script_hex):
    # The first byte represents the threshold (m), encoded as OP_(m + 80)
    m = int(script_hex[:2], 16) - 80

    # Parse the script to find the public keys
    # Each public key is prefixed with '21' indicating its length (33 bytes)
    script_body = script_hex[2:]  # Start after the m OP code
    public_keys = []
    while script_body:
        # Check for the prefix '21' indicating the start of a public key
        if script_body[:2] == "21":
            key = script_body[2:68]  # Extract the next 66 characters as the public key
            public_keys.append(key)
            script_body = script_body[68:]  # Move past the extracted key
        else:
            break  # Exit loop if no '21' prefix is found

    # The last two bytes before OP_CHECKMULTISIG represent the total number of keys (n)
    n = int(script_hex[-4:-2], 16) - 80

    return m, n, public_keys


def m_of_n(psbt_input):
    witness_script = psbt_input.get("witness_script")
    d = {"m": 1, "n": 1, "public_keys": []}
    if witness_script:
        m, n, public_keys = parse_witness_script(witness_script)
        if m is not None and n is not None and m <= n:
            d = {"m": m, "n": n, "public_keys": public_keys}
    return d


def get_psbt_simple_json(psbt: bdk.PartiallySignedTransaction):
    psbt_json = json.loads(psbt.json_serialize())
    inputs = []

    # Iterate through the inputs in the PSBT
    for input in psbt_json.get("inputs", []):
        # Check for signatures in partial_sigs
        d = {"bip32_derivation": input.get("bip32_derivation", [])}

        d.update(m_of_n(input))

        if not d["public_keys"]:
            d["public_keys"] = [l[0] for l in d.get("bip32_derivation", [])]

        if not d["public_keys"]:
            d["public_keys"] = [None for i in range(d["n"])]

        # Check for a non-empty final_script_sig or final_script_witness
        if input.get("final_script_sig"):
            d["signature"] = input.get("final_script_sig")
        elif input.get("final_script_witness"):
            d["signature"] = input.get("final_script_witness")
        elif input.get("partial_sigs"):
            d["partial_sigs"] = input["partial_sigs"]

        if isinstance(d.get("signature"), list):
            d["signature"] = "".join(d["signature"])

        def get_fingerprint_of_pubkey(pubkey):
            for l in d.get("bip32_derivation", []):
                if l[0] == pubkey:
                    return l[1][0]

        def get_derivation_of_pubkey(pubkey):
            for l in d.get("bip32_derivation", []):
                if l[0] == pubkey:
                    return l[1][1]

        d["summary"] = {
            public_key: {
                "partial_sigs": bool(d.get("partial_sigs", {}).get(public_key)),
                "signature": bool(d.get("signature", {})),
                "fingerprint": get_fingerprint_of_pubkey(public_key),
                "derivation": get_derivation_of_pubkey(public_key),
            }
            for public_key in d["public_keys"]
        }

        inputs.append(d)

    return {"inputs": inputs}


def get_txouts_from_inputs(
    psbt: bdk.PartiallySignedTransaction,
) -> Dict[str, bdk.TxOut]:
    tx_outs = {}
    psbt_json = json.loads(psbt.json_serialize())
    for inp, json_inp in zip(psbt.extract_tx().input(), psbt_json["inputs"]):
        # get which actual outpoint
        prev_out = OutPoint.from_bdk(inp.previous_output)
        # fetch this outpoint from the json
        json_prev_out = json_inp.get("non_witness_utxo", {}).get("output", {})
        if json_prev_out:
            script_pubkey = bdk.Script(
                bytes.fromhex(json_prev_out[prev_out.vout]["script_pubkey"])
            )
            tx_outs[str(prev_out)] = bdk.TxOut(
                script_pubkey=script_pubkey, value=json_prev_out[prev_out.vout]["value"]
            )
    return tx_outs


def get_sent_and_change_outputs(
    psbt: bdk.PartiallySignedTransaction,
) -> Dict[int, bdk.TxOut]:
    sent_tx_outs = {}
    change_tx_outs = {}
    psbt_json = json.loads(psbt.json_serialize())
    for i, (txout, json_txout) in enumerate(
        zip(psbt.extract_tx().output(), psbt_json["outputs"])
    ):
        derivation_tuple = json_txout["bip32_derivation"]
        if not derivation_tuple:
            sent_tx_outs[i] = txout
        else:
            key_origin = derivation_tuple[0][1][1]
            *first_part, change_index, address_index = key_origin.split("/")
            if change_index == "1":
                change_tx_outs[i] = txout
            else:
                sent_tx_outs[i] = txout
    return sent_tx_outs, change_tx_outs


def calculate_sent_change_amounts(
    psbt: bdk.PartiallySignedTransaction,
) -> Tuple[List[int], List[int]]:
    sent_tx_outs, change_tx_outs = get_sent_and_change_outputs(psbt)
    sent_values = [txout.value for txout in sent_tx_outs.values()]
    change_values = [txout.value for txout in change_tx_outs.values()]

    return sent_values, change_values


def estimate_tx_weight(input_mn_tuples, num_outputs, include_signatures=True):
    """
    Estimate the weight of a SegWit transaction in weight units, including support for multiple inputs with
    varying m-of-n multisignature configurations.

    Args:
    input_mn_tuples (list of tuples): A list where each tuple represents an input with (m, n) configuration.
    num_outputs (int): Number of outputs in the transaction.
    include_signatures (bool): Whether to include the size of signatures in the estimate.

    Returns:
    int: Estimated transaction weight in weight units.
    """
    # Transaction overheads
    version_size = 4
    segwit_marker_and_flag_size = 2
    locktime_size = 4

    # Input components
    outpoint_size = 36  # txid (32 bytes) + vout index (4 bytes)
    script_length_size = 1  # Size of the script length field
    sequence_size = 4  # Size of the sequence field
    base_input_size = outpoint_size + sequence_size  # Excluding scriptSig and witness

    # Output components
    output_value_size = 8  # Size of the value field
    output_script_length_size = 1  # Size of the script length field
    p2wpkh_script_size = 22  # P2WPKH script size
    base_output_size = (
        output_value_size + output_script_length_size + p2wpkh_script_size
    )

    # Witness components
    witness_stack_items_size = 1  # Size byte for the number of witness stack items
    average_signature_size = 72  # Approximate size of a signature
    average_pubkey_size = 33  # Size of a compressed public key

    # Calculate total witness data size
    total_witness_data_size = 0
    for m, n in input_mn_tuples:
        witness_data_size_per_input = (
            witness_stack_items_size
            + (m * (1 + average_signature_size))
            + (n * (1 + average_pubkey_size))
        )
        total_witness_data_size += (
            witness_data_size_per_input if include_signatures else 0
        )

    # Calculate base transaction size (excluding witness data)
    num_inputs = len(input_mn_tuples)
    base_tx_size_without_witness = (
        version_size
        + segwit_marker_and_flag_size
        + locktime_size
        + num_inputs * (base_input_size + script_length_size)
        + num_outputs * base_output_size
    )

    # Calculate transaction weight
    # Non-witness data is weighted as 4 units per byte, witness data as 1 unit per byte
    tx_weight = (base_tx_size_without_witness * 4) + total_witness_data_size

    return tx_weight


class FeeInfo:
    def __init__(self, fee_amount, tx_size, is_estimated=False) -> None:
        self.fee_amount = fee_amount
        self.tx_size = tx_size
        self.is_estimated = is_estimated

    def fee_rate(self):
        return self.fee_amount / self.tx_size


def estimate_segwit_fee_rate_from_psbt(psbt: bdk.PartiallySignedTransaction) -> FeeInfo:
    """
    Estimate the fee rate of a SegWit transaction from a serialized PSBT JSON.

    Args:
    psbt_json_str (str): The serialized PSBT JSON string.

    Returns:
    float: Estimated fee rate in satoshis per byte.
    """

    # Get the simplified JSON representation of the PSBT
    psbt_json = get_psbt_simple_json(psbt)

    input_mn_tuples = [(inp["m"], inp["n"]) for inp in psbt_json["inputs"]]

    # Estimate the size of the transaction
    # This part requires the transaction size estimation logic, which might need information about inputs and outputs
    # For simplicity, let's assume you have a function estimate_tx_size(psbt_data) that can estimate the size
    tx_size = estimate_tx_weight(input_mn_tuples, len(psbt.extract_tx().output())) / 4

    return FeeInfo(psbt.fee_amount(), tx_size, is_estimated=True)


def get_likely_origin_wallet(input_outpoints: List[OutPoint], wallets) -> "Wallet":

    for wallet in wallets:
        wallet_outpoints: List[OutPoint] = [
            OutPoint.from_bdk(utxo.outpoint) for utxo in wallet.bdkwallet.list_unspent()
        ]
        for outpoint in input_outpoints:
            if outpoint in wallet_outpoints:
                return wallet
