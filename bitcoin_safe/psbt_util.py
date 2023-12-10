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


def psbt_simple_json(psbt: bdk.PartiallySignedTransaction):
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


def get_txouts_from_inputs(psbt: bdk.PartiallySignedTransaction):
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
            tx_outs[prev_out] = bdk.TxOut(
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
            derivation_path = derivation_tuple[0][1][1]
            *first_part, change_index, address_index = derivation_path.split("/")
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


def estimate_segwit_tx_size(num_inputs, num_outputs, n=1, m=1, include_signatures=True):
    """
    Estimate the size of a SegWit transaction in bytes, including support for m-of-n multisignature inputs.

    Args:
    num_inputs (int): Number of inputs in the transaction.
    num_outputs (int): Number of outputs in the transaction.
    n (int): Total number of signatures in a multisignature input.
    m (int): Required number of signatures in a multisignature input.
    include_signatures (bool): Whether to include the size of signatures in the estimate.

    Returns:
    int: Estimated transaction size in bytes.
    """
    # Constants for size calculations
    base_tx_size = 10  # base transaction size
    base_input_size = 32  # base size per input without signatures
    signature_size = 72  # approximate size of a single signature
    pubkey_size = 33  # size of a compressed public key

    # Size of the scriptSig part of a multisig input
    script_sig_size = (
        1 + (m * signature_size) + (n * pubkey_size) + 3
    )  # 3 bytes for m, n and OP_CHECKMULTISIG

    # Total size per input
    input_size = base_input_size + (script_sig_size if include_signatures else 0)

    # Size per output
    output_size = 34  # size per output

    # Witness data adds about 0.25 weight units per byte, or 1/4 the size in vbytes
    # For multisig, witness data is just the signatures
    witness_data_size = num_inputs * (m * signature_size if include_signatures else 0)
    witness_size = witness_data_size // 4

    # Calculate total transaction size
    total_size = (
        base_tx_size
        + (num_inputs * input_size)
        + (num_outputs * output_size)
        + witness_size
    )

    return total_size
