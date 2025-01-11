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


import os
import sys
from typing import Any, Dict, List, Tuple, Union

import pefile


def improved_locate_offset_in_pe(pe: pefile.PE, offset: int) -> str:
    """
    Locate `offset` (a file offset, *not* an RVA) in a PE file.
    Breaks down headers into subregions: DOS header, NT signature,
    COFF file header, Optional header, Section table, Section data, Overlay, etc.
    """
    # ----- 1) DOS Header -----
    dos_end = pe.DOS_HEADER.e_lfanew  # typically ~0x80
    if offset < dos_end:
        return "DOS Header"

    # ----- 2) NT Signature (4 bytes, typically 'PE\\0\\0') -----
    nt_signature_start = pe.DOS_HEADER.e_lfanew
    nt_signature_end = nt_signature_start + 4
    if nt_signature_start <= offset < nt_signature_end:
        return "NT Signature ('PE\\0\\0')"

    # ----- 3) COFF File Header (usually 20 bytes) -----
    file_header_start = nt_signature_end
    file_header_size = pe.FILE_HEADER.sizeof()  # typically 20
    file_header_end = file_header_start + file_header_size
    if file_header_start <= offset < file_header_end:
        return "COFF File Header"

    # ----- 4) Optional Header -----
    optional_header_start = file_header_end
    optional_header_end = optional_header_start + pe.FILE_HEADER.SizeOfOptionalHeader
    if optional_header_start <= offset < optional_header_end:
        return "Optional Header"

    # ----- 5) Section Table (one entry per section, 40 bytes each) -----
    section_table_start = optional_header_end
    section_table_size = pe.FILE_HEADER.NumberOfSections * 40
    section_table_end = section_table_start + section_table_size
    if section_table_start <= offset < section_table_end:
        return "Section Table"

    # ----- Check each section's raw data range -----
    for section in pe.sections:
        start = section.PointerToRawData
        end = start + section.SizeOfRawData
        if start <= offset < end:
            name = section.Name.rstrip(b"\x00").decode(errors="ignore")
            return f"Section '{name}'"

    # ----- Overlay / Extra Data? -----
    last_section_end = max((sec.PointerToRawData + sec.SizeOfRawData) for sec in pe.sections)
    if offset >= last_section_end:
        return "Overlay / Extra Data"

    return "Unknown (alignment padding or unexpected region)"


def compare_section_data(pe1: pefile.PE, pe2: pefile.PE) -> bool:
    """
    Compare only the raw data of each section (e.g. .text, .rdata, .data).
    Ignore all headers and any overlay. Return True if all sections match.
    """
    # Must have same number of sections
    if pe1.FILE_HEADER.NumberOfSections != pe2.FILE_HEADER.NumberOfSections:
        print("Section count differs.")
        return False

    # Compare each section by index
    for i, (sec1, sec2) in enumerate(zip(pe1.sections, pe2.sections)):
        # Compare section names (stripped of trailing nulls)
        name1 = sec1.Name.strip(b"\x00")
        name2 = sec2.Name.strip(b"\x00")
        if name1 != name2:
            print(f"Section {i} name differs: {name1} vs {name2}")
            return False

        # Compare the actual raw data in each section
        data1 = sec1.get_data()
        data2 = sec2.get_data()
        if data1 != data2:
            print(f"Section {name1} differs in raw data.")
            return False

    return True


def compare_optional_header_fields(pe1: pefile.PE, pe2: pefile.PE) -> List[Dict[str, Any]]:
    """
    Compare each named field in the Optional Header of two PE files.
    Returns a list of changes in the format: "FieldName: old_value -> new_value".
    """
    changes = []

    # We'll gather typical attributes from the OPTIONAL_HEADER object.
    # You could refine this if you only want certain fields.
    possible_fields = dir(pe1.OPTIONAL_HEADER)
    # Filter out built-ins/private/methods
    fields = [f for f in possible_fields if not f.startswith("_")]

    for field_name in fields:
        try:
            val1 = getattr(pe1.OPTIONAL_HEADER, field_name)
            val2 = getattr(pe2.OPTIONAL_HEADER, field_name)
        except AttributeError:
            # If some attribute doesn't exist on both, skip
            continue

        if val1 != val2:
            changes.append({"file1": val1, "file2": val2})

    return changes


def _find_mismatch_offsets(
    raw1: bytes, raw2: bytes, max_differences: int = 10
) -> List[Dict[str, Union[int, bool]]]:
    """
    Identify up to `max_differences` byte offsets where raw1 and raw2 differ.
    Returns a list of dictionaries, each describing a mismatch:
      [
        {
          'offset': <int>,      # The differing byte offset (None if it's a size-difference record)
          'left_byte': <int>,   # Byte value from raw1 (0..255)
          'right_byte': <int>   # Byte value from raw2 (0..255)
        },
        {
          'size_diff': True,    # Special marker for file-size difference
          'left_size': <int>,
          'right_size': <int>
        },
        ...
      ]
    """
    mismatches: List[Dict[str, Union[int, bool]]] = []

    # We'll compare up to the smaller of the two lengths
    limit = min(len(raw1), len(raw2))
    count = 0

    for i in range(limit):
        b1 = raw1[i]
        b2 = raw2[i]
        if b1 != b2:
            mismatches.append({"offset": i, "left_byte": b1, "right_byte": b2})
            count += 1
            if count >= max_differences:
                break

    # If there's a difference in file sizes, record that too
    if len(raw1) != len(raw2):
        mismatches.append({"size_diff": True, "left_size": len(raw1), "right_size": len(raw2)})

    return mismatches


def compare_raw_data(pe1: pefile.PE, pe2: pefile.PE) -> List[Dict[str, Union[str, int]]]:
    """
    Compare the raw file data of two PE files (pe1.__data__ vs pe2.__data__).
    Return a list of mismatch records, each including:
        {
          'offset': '0x....',     # Hex offset in the second file (if applicable)
          'region': <str>,        # Where in the PE the offset lies
          'left_byte': '0x..',    # (Hex string) Byte from the first file
          'right_byte': '0x..'    # (Hex string) Byte from the second file
        }
    or, for a size difference:
        {
          'offset': 'N/A',
          'region': 'File size difference',
          'comment': 'Left: 123 vs Right: 456'
        }
    """
    diffs: List[Dict[str, Union[str, int]]] = []

    raw1 = pe1.__data__
    raw2 = pe2.__data__

    if raw1 == raw2:
        return diffs  # No differences at all

    # Gather structured mismatches
    mismatch_list = _find_mismatch_offsets(raw1, raw2, max_differences=10)

    for mismatch in mismatch_list:
        # If it's a special record indicating file-size difference
        if "size_diff" in mismatch:
            diffs.append(
                {
                    "offset": "N/A",
                    "region": "File size difference",
                    "comment": f"Left: {mismatch['left_size']} vs Right: {mismatch['right_size']}",
                }
            )
            continue

        # Otherwise, it's a byte mismatch
        offset_int = mismatch["offset"]  # an integer
        left_byte_val = mismatch["left_byte"]
        right_byte_val = mismatch["right_byte"]

        # Identify region in pe2 (the "signed" file, presumably)
        region = improved_locate_offset_in_pe(pe2, offset_int)

        # Build the final mismatch record
        diffs.append(
            {
                "offset": f"0x{offset_int:08X}",
                "region": region,
                "left_byte": f"0x{left_byte_val:02X}",
                "right_byte": f"0x{right_byte_val:02X}",
            }
        )

    return diffs


def zero_out_optional_header(pe: pefile.PE) -> None:
    """
    Zero out all bytes in the Optional Header portion of `pe.__data__`.
    WARNING: This corrupts the PE file if you try to save it back to disk.
             Only use it for in-memory comparisons if you want to ignore
             Optional Header differences.
    """
    # 1) Find the start of the NT signature ("PE\0\0")
    nt_signature_offset = pe.DOS_HEADER.e_lfanew
    # 2) Skip 4 bytes for the signature, then the size of the File Header
    file_header_size = pe.FILE_HEADER.sizeof()  # typically 20 bytes
    optional_header_start = nt_signature_offset + 4 + file_header_size

    # 3) Determine how many bytes the Optional Header has
    optional_header_size = pe.FILE_HEADER.SizeOfOptionalHeader
    optional_header_end = optional_header_start + optional_header_size

    # 4) Convert pe.__data__ to a mutable bytearray
    new_data = bytearray(pe.__data__)

    # 5) Zero out the Optional Header region (within file bounds)
    for i in range(optional_header_start, min(optional_header_end, len(new_data))):
        new_data[i] = 0

    # 6) Assign the modified data back to pe.__data__
    pe.__data__ = bytes(new_data)

    # (Optional) If you're purely doing a raw comparison and won't parse
    # more fields afterward, this might be enough. But note that if you call
    # other pefile methods that rely on the optional header, they could break
    # or produce incorrect results.


def compare(unsigned_path: str, signed_path: str) -> Tuple[bool, List[Dict[str, Union[str, int]]]]:
    """
    High-level comparison:
      1. Compare section data (MUST be == true).
      2. Compare full raw data, highlighting mismatches by offset. Insignificant changes may occur here
    """

    pe1 = pefile.PE(unsigned_path)
    pe2 = pefile.PE(signed_path)

    # print("Compare sections...  (MUST match)")
    critical_comparision = compare_section_data(pe1, pe2)
    # print(f"{critical_comparision=}")

    # print("Compare raw file data (entire PE), Insignificant changes may occur here ...")
    zero_out_optional_header(pe1)
    zero_out_optional_header(pe2)
    raw_diffs = compare_raw_data(pe1, pe2)
    # if not raw_diffs:
    #     print("No raw data differences.")
    # else:
    #     print("Raw data differences found:")
    #     for d in raw_diffs:
    #         print(" -", d)

    # print("[3] Compare optional header fields...")
    # opt_changes = compare_optional_header_fields(pe1, pe2)
    # if not opt_changes:
    #     print("No changes in the Optional Header fields.")
    # else:
    #     print("Changes in Optional Header fields:")
    #     for ch in opt_changes:
    #         print(f" - {ch}")

    return critical_comparision, raw_diffs  # , opt_changes


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python ensure-signed-file-integrity.py <unsigned-folder> <signed-folder>")
        sys.exit(1)

    unsigned_folder = sys.argv[1]
    signed_folder = sys.argv[2]
    raw_diffs = None

    if not os.path.isdir(unsigned_folder):
        print(f"Error: '{unsigned_folder}' is not a directory.")
        sys.exit(1)
    if not os.path.isdir(signed_folder):
        print(f"Error: '{signed_folder}' is not a directory.")
        sys.exit(1)

    # Gather files in the unsigned folder
    unsigned_files = os.listdir(unsigned_folder)
    unsigned_files.sort()

    # Iterate over each file in the unsigned folder
    for filename in unsigned_files:
        unsigned_path = os.path.join(unsigned_folder, filename)

        # Skip subfolders or non-files
        if not os.path.isfile(unsigned_path):
            continue

        signed_path = os.path.join(signed_folder, filename)
        if not os.path.isfile(signed_path):
            # No matching file in signed folder => fail immediately
            print(f"ERROR: Could not find matching file '{filename}' in '{signed_folder}'.")
            sys.exit(1)

        # Run comparison
        print(f"Comparing: {unsigned_path} to {signed_path}")
        critical_comparison, raw_diffs = compare(unsigned_path, signed_path)

        # If critical comparison fails => fail workflow right now
        if not critical_comparison:
            print(f"ERROR: Critical mismatch between '{unsigned_path}' and '{signed_path}'.")
            sys.exit(1)

    # If we reach here, all files matched

    print(f"Insignificant differences: {raw_diffs}")
    print(
        f"Success:  All {len(unsigned_files)} files match! PE sections are identical and any optional-header differences have been ignored."
    )
    sys.exit(0)
