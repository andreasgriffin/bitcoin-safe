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

import binascii
import json
from typing import Any, Dict, List, Optional, Tuple

import bdkpython as bdk

JsonDict = Dict[str, Any]


class ChangeSetConverter:
    """
    Convert between bdk.ChangeSet and a JSON-serializable dict structure.
    """

    # ---------------------------
    # Small conversion utilities
    # ---------------------------

    @staticmethod
    def _bytes_to_hex(b: bytes) -> str:
        return b.hex()

    @staticmethod
    def _hex_to_bytes(h: str) -> bytes:
        try:
            return binascii.unhexlify(h)
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"Invalid hex string: {h!r}") from e

    @staticmethod
    def _txid_to_hex(txid: bdk.Txid) -> str:
        # bdk.Txid typically has serialize(); accept string fallback
        try:
            return ChangeSetConverter._bytes_to_hex(txid.serialize())
        except AttributeError:
            # already a string, or incompatible type
            if isinstance(txid, str):
                return txid
            raise TypeError(f"Unsupported txid type: {type(txid)}")

    @staticmethod
    def _hex_to_txid(h: str) -> bdk.Txid:
        # Prefer from_bytes if hex, else let bdk.Txid(h) handle non-hex encodings
        try:
            return bdk.Txid.from_bytes(ChangeSetConverter._hex_to_bytes(h))
        except ValueError:
            # Not hex -> let constructor parse
            return bdk.Txid(h)

    @staticmethod
    def _blockhash_to_hex(bh: Optional[bdk.BlockHash]) -> Optional[str]:
        if bh is None:
            return None
        return ChangeSetConverter._bytes_to_hex(bh.serialize())

    @staticmethod
    def _hex_to_blockhash(h: Optional[str]) -> Optional[bdk.BlockHash]:
        if h is None:
            return None
        return bdk.BlockHash.from_bytes(ChangeSetConverter._hex_to_bytes(h))

    @staticmethod
    def _network_to_string(net: Optional[bdk.Network]) -> Optional[str]:
        return None if net is None else net.name

    @staticmethod
    def _string_to_network(name: Optional[str]) -> Optional[bdk.Network]:
        if name is None:
            return None
        try:
            return bdk.Network[name]
        except KeyError as e:
            raise ValueError(f"Unknown network name: {name!r}") from e

    @staticmethod
    def _canonical_outpoint_key(txid_hex: str, vout: int) -> str:
        # Keep schema (JSON string key) but make it canonical and stable
        return json.dumps({"txid": txid_hex, "vout": vout}, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _parse_outpoint_key(key: str) -> Tuple[str, int]:
        obj = json.loads(key)
        return obj["txid"], int(obj["vout"])

    # -----------
    # TO DICT
    # -----------

    @staticmethod
    def to_dict(changeset: bdk.ChangeSet) -> Dict[str, Any]:
        """
        Serialize a bdk.ChangeSet into a plain Python dict (JSON-safe).
        """

        def _serialize_descriptor(descriptor: Optional[bdk.Descriptor]) -> Optional[str]:
            return None if descriptor is None else str(descriptor)

        def _serialize_chainchange(cc: bdk.ChainChange) -> Dict[str, Any]:
            return {"height": cc.height, "hash": ChangeSetConverter._blockhash_to_hex(cc.hash)}

        def _serialize_local_chain(local_chain: bdk.LocalChainChangeSet) -> Dict[str, Any]:
            return {"changes": [_serialize_chainchange(cc) for cc in local_chain.changes]}

        def _serialize_tx(tx: bdk.Transaction) -> str:
            return ChangeSetConverter._bytes_to_hex(tx.serialize())

        def _serialize_outpoint(hop: bdk.HashableOutPoint) -> Dict[str, Any]:
            op = hop.outpoint()
            return {
                "txid": ChangeSetConverter._txid_to_hex(op.txid),
                "vout": op.vout,
            }

        def _serialize_txout(txout: bdk.TxOut) -> Dict[str, Any]:
            script_obj: bdk.Script = txout.script_pubkey
            script_bytes = script_obj.to_bytes()
            return {
                "value": txout.value.to_sat(),
                "script_pubkey": ChangeSetConverter._bytes_to_hex(script_bytes),
            }

        def _serialize_tx_graph(tx_graph: bdk.TxGraphChangeSet) -> Dict[str, Any]:
            txs_list = [_serialize_tx(tx) for tx in tx_graph.txs]

            txouts_dict: Dict[str, Dict[str, Any]] = {}
            for hop, txout in tx_graph.txouts.items():
                op = _serialize_outpoint(hop)
                key = ChangeSetConverter._canonical_outpoint_key(op["txid"], op["vout"])
                txouts_dict[key] = _serialize_txout(txout)

            anchors_list: List[Dict[str, Any]] = []
            for anchor in tx_graph.anchors:
                cbt = anchor.confirmation_block_time
                block_id = cbt.block_id
                bh_hex = ChangeSetConverter._blockhash_to_hex(block_id.hash)
                block_id_obj = {"height": block_id.height, "hash": bh_hex}
                cbt_obj = {"block_id": block_id_obj, "confirmation_time": cbt.confirmation_time}
                txid_hex = ChangeSetConverter._txid_to_hex(anchor.txid)
                anchors_list.append({"confirmation_block_time": cbt_obj, "txid": txid_hex})

            # Support all three maps
            last_seen_dict: Dict[str, int] = {
                ChangeSetConverter._txid_to_hex(txid_obj): height
                for txid_obj, height in tx_graph.last_seen.items()
            }
            # Use getattr to be compatible with older bdk builds (missing attrs)
            first_seen_src = getattr(tx_graph, "first_seen", {})
            last_evicted_src = getattr(tx_graph, "last_evicted", {})

            first_seen_dict: Dict[str, int] = {
                ChangeSetConverter._txid_to_hex(txid_obj): height
                for txid_obj, height in first_seen_src.items()
            }
            last_evicted_dict: Dict[str, int] = {
                ChangeSetConverter._txid_to_hex(txid_obj): height
                for txid_obj, height in last_evicted_src.items()
            }

            return {
                "txs": txs_list,
                "txouts": txouts_dict,
                "anchors": anchors_list,
                "last_seen": last_seen_dict,
                "first_seen": first_seen_dict,
                "last_evicted": last_evicted_dict,
            }

        def _serialize_indexer(indexer: bdk.IndexerChangeSet) -> Dict[str, Any]:
            lr: Dict[str, int] = {}
            for did_obj, idx in indexer.last_revealed.items():
                lr[ChangeSetConverter._bytes_to_hex(did_obj.serialize())] = idx
            return {"last_revealed": lr}

        out: Dict[str, Any] = {
            "descriptor": _serialize_descriptor(changeset.descriptor()),
            "change_descriptor": _serialize_descriptor(changeset.change_descriptor()),
            "network": ChangeSetConverter._network_to_string(changeset.network()),
            "local_chain": _serialize_local_chain(changeset.localchain_changeset()),
            "tx_graph": _serialize_tx_graph(changeset.tx_graph_changeset()),
            "indexer": _serialize_indexer(changeset.indexer_changeset()),
        }
        return out

    # -------------
    # FROM DICT
    # -------------

    @staticmethod
    def from_dict(parsed_json: Dict[str, Any]) -> bdk.ChangeSet:
        """
        Deserialize a plain Python dict (as produced by to_dict) into a bdk.ChangeSet.
        """

        def _deserialize_descriptor(
            descriptor_str: Optional[str], network: Optional[bdk.Network]
        ) -> Optional[bdk.Descriptor]:
            if descriptor_str is None:
                return None
            if network is None:
                return None
            # If your bdk has a dedicated constructor, keep as-is:
            return bdk.Descriptor(descriptor_str, network)

        def _deserialize_chainchange(data: Dict[str, Any]) -> bdk.ChainChange:
            return bdk.ChainChange(
                height=int(data["height"]),
                hash=ChangeSetConverter._hex_to_blockhash(data.get("hash")),
            )

        def _deserialize_local_chain(data: Dict[str, Any]) -> bdk.LocalChainChangeSet:
            changes_list = data.get("changes", [])
            cc_objs: List[bdk.ChainChange] = [_deserialize_chainchange(cc) for cc in changes_list]
            return bdk.LocalChainChangeSet(changes=cc_objs)

        def _deserialize_tx(hexstr: str) -> bdk.Transaction:
            raw = ChangeSetConverter._hex_to_bytes(hexstr)
            return bdk.Transaction(raw)

        def _deserialize_outpoint(key_str: str) -> bdk.HashableOutPoint:
            txid_hex, vout = ChangeSetConverter._parse_outpoint_key(key_str)
            txid_obj = ChangeSetConverter._hex_to_txid(txid_hex)
            outpoint = bdk.OutPoint(txid=txid_obj, vout=int(vout))
            return bdk.HashableOutPoint(outpoint=outpoint)

        def _deserialize_txout(data: Dict[str, Any]) -> bdk.TxOut:
            value = int(data["value"])
            script_hex = data["script_pubkey"]
            script_bytes = ChangeSetConverter._hex_to_bytes(script_hex)

            # Prefer a stable initializer; fall back if needed
            try:
                script_obj = bdk.Script(script_bytes)
            except AttributeError:
                script_obj = bdk.Script(raw_output_script=script_bytes)  # legacy path

            return bdk.TxOut(value=bdk.Amount.from_sat(value), script_pubkey=script_obj)

        def _deserialize_tx_graph(data: Dict[str, Any]) -> bdk.TxGraphChangeSet:
            tx_hex_list = data.get("txs", [])
            tx_objs: List[bdk.Transaction] = [_deserialize_tx(h) for h in tx_hex_list]

            txouts_data = data.get("txouts", {})
            txouts_dict: Dict[bdk.HashableOutPoint, bdk.TxOut] = {}
            for key_str, txout_data in txouts_data.items():
                hop = _deserialize_outpoint(key_str)
                txouts_dict[hop] = _deserialize_txout(txout_data)

            anchors_list: List[bdk.Anchor] = []
            for anc in data.get("anchors", []):
                cbt_data = anc["confirmation_block_time"]
                block_id_data = cbt_data["block_id"]

                block_hash = ChangeSetConverter._hex_to_blockhash(block_id_data.get("hash"))
                if not block_hash:
                    raise ValueError(f"{anc=} not present")
                block_id_obj = bdk.BlockId(
                    height=int(block_id_data["height"]),
                    hash=block_hash,
                )

                cbt_obj = bdk.ConfirmationBlockTime(
                    block_id=block_id_obj,
                    confirmation_time=int(cbt_data["confirmation_time"]),
                )

                txid_obj = ChangeSetConverter._hex_to_txid(anc["txid"])
                anchors_list.append(bdk.Anchor(confirmation_block_time=cbt_obj, txid=txid_obj))

            # All three maps → Dict[bdk.Txid, int]
            def _txid_height_map(d: Dict[str, Any]) -> Dict[bdk.Txid, int]:
                out: Dict[bdk.Txid, int] = {}
                for txid_hex, height in d.items():
                    out[ChangeSetConverter._hex_to_txid(txid_hex)] = int(height)
                return out

            last_seen_dict = _txid_height_map(data.get("last_seen", {}))
            first_seen_dict = _txid_height_map(data.get("first_seen", {}))
            last_evicted_dict = _txid_height_map(data.get("last_evicted", {}))

            # Prefer new signature; fall back if using an older bdk build
            return bdk.TxGraphChangeSet(
                txs=tx_objs,
                txouts=txouts_dict,
                anchors=anchors_list,
                last_seen=last_seen_dict,
                first_seen=first_seen_dict,
                last_evicted=last_evicted_dict,
            )

        def _deserialize_indexer(data: Dict[str, Any]) -> bdk.IndexerChangeSet:
            lr_data = data.get("last_revealed", {})
            lr_dict: Dict[bdk.DescriptorId, int] = {}
            for did_hex, idx in lr_data.items():
                did_obj = bdk.DescriptorId.from_bytes(ChangeSetConverter._hex_to_bytes(did_hex))
                lr_dict[did_obj] = int(idx)
            return bdk.IndexerChangeSet(last_revealed=lr_dict)

        network_obj = ChangeSetConverter._string_to_network(parsed_json.get("network"))

        descr = _deserialize_descriptor(parsed_json.get("descriptor"), network_obj)
        change_descr = _deserialize_descriptor(parsed_json.get("change_descriptor"), network_obj)
        local_chain_obj = _deserialize_local_chain(parsed_json["local_chain"])
        tx_graph_obj = _deserialize_tx_graph(parsed_json["tx_graph"])
        indexer_obj = _deserialize_indexer(parsed_json["indexer"])

        changeset = bdk.ChangeSet.from_descriptor_and_network(
            descriptor=descr,
            change_descriptor=change_descr,
            network=network_obj,
        )
        changeset = bdk.ChangeSet.from_merge(
            changeset, bdk.ChangeSet.from_local_chain_changes(local_chain_changes=local_chain_obj)
        )
        changeset = bdk.ChangeSet.from_merge(
            changeset, bdk.ChangeSet.from_tx_graph_changeset(tx_graph_changeset=tx_graph_obj)
        )
        changeset = bdk.ChangeSet.from_merge(
            changeset, bdk.ChangeSet.from_indexer_changeset(indexer_changes=indexer_obj)
        )
        return changeset
