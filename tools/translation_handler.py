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


import csv
import logging
import operator
import shlex
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from typing import List, Tuple, Union

from bitcoin_safe_lib.util import threadtable

from bitcoin_safe.gui.qt.language_chooser import FLAGS

logger = logging.getLogger(__name__)


def run_local(cmd) -> CompletedProcess:
    completed_process = subprocess.run(shlex.split(cmd), check=True)
    return completed_process


# https://www.fincher.org/Utilities/CountryLanguageList.shtml
class TranslationHandler:
    def __init__(
        self,
        module_name,
        prefix="app",
    ) -> None:
        self.module_name = module_name
        self.ts_folder = Path(module_name) / "gui" / "locales"
        self.prefix = prefix

        autodetected_lang_files = list(self.ts_folder.glob("*.ts"))
        self.languages = [file.stem[len(prefix) + 1 :] for file in autodetected_lang_files]

        logger.info("=" * 20)
        logger.info(
            f"""
Translate all following lines   to the following languages
 {self.languages}
Information context:  A bitcoin only bitcoin wallet.   So a term like "KYC Exchange"  means a trading place, that requires KYC. A wallet is a software that shows the balances on bitcoin addresses that belong to the user.  An address is a bitcoin address. 
Formatting instructions:
- no bullets points.  
- preserve the linebreaks of each line perfectly! keep the newline after each translated line.
- leave the brackets {{}} and their content unchanged
- group by language  (add 2 linebreaks after the language caption)
- please keep the linebreaks as in the originals
Content to translate:
"""
        )
        logger.info("=" * 20)

        for language in self.languages:
            assert language in FLAGS

    def delete_po_files(self):
        for file in self.ts_folder.glob("*.po"):
            file.unlink()

    def get_all_python_files(self, additional_dirs=[".venv/lib"]) -> List[str]:
        all_dirs = [self.module_name] + additional_dirs

        python_files: List[str] = []
        for d in all_dirs:
            python_files += [str(file) for file in Path(d).rglob("*.py")]
        return python_files

    def get_all_ts_files(self) -> List[str]:
        python_files = [str(file) for file in self.ts_folder.rglob("*.ts")]
        return python_files

    def _ts_file(self, language: str) -> Path:
        return self.ts_folder / f"{self.prefix}_{language}.ts"

    @staticmethod
    def sort_csv(input_file: Path, output_file: Path, sort_columns: Union[Tuple[str, ...], List[str]]):
        """
        Sorts a CSV file by specified columns and writes the sorted data to another CSV file.

        Parameters:
            input_file (Path): The input CSV file path.
            output_file (Path): The output CSV file path.
            sort_columns (Tuple[str, ...]): A tuple of column names to sort the CSV data by (in priority order).
        """
        # Read the CSV file into a list of dictionaries
        with open(str(input_file), mode="r", newline="", encoding="utf-8") as infile:
            reader = csv.DictReader(infile)
            rows = list(reader)

        # Validate that all sort columns are in the fieldnames
        fieldnames = reader.fieldnames
        assert fieldnames
        for col in sort_columns:
            if col not in fieldnames:
                raise ValueError(f"Column '{col}' not found in CSV file")

        # Sort the rows by the specified columns (in priority order)
        sorted_rows = sorted(rows, key=operator.itemgetter(*sort_columns))

        # Write the sorted data to the output CSV file
        with open(str(output_file), mode="w", newline="", encoding="utf-8") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(sorted_rows)

    def update_translations_from_py(self):
        python_files = self.get_all_python_files()
        print(f"Found {len(python_files)} python files for translation")

        def process(language):
            ts_file = self._ts_file(language)
            run_local(f"pylupdate6  {' '.join(python_files)} -no-obsolete  -ts {ts_file}")  # -no-obsolete
            run_local(f"ts2po {ts_file}  -o {ts_file.with_suffix('.po')}")
            run_local(f"po2csv {ts_file.with_suffix('.po')}  -o {ts_file.with_suffix('.csv')}")
            self.sort_csv(
                ts_file.with_suffix(".csv"),
                ts_file.with_suffix(".csv"),
                sort_columns=["target", "location", "source"],
            )

        threadtable(process, self.languages)

        self.delete_po_files()
        self.compile()

    @staticmethod
    def quote_csv(input_file, output_file):
        # Read the CSV content from the input file
        with open(input_file, newline="") as infile:
            reader = csv.reader(infile)
            rows = list(reader)

        # Write the CSV content with quotes around each item to the output file
        with open(output_file, "w", newline="") as outfile:
            writer = csv.writer(outfile, quoting=csv.QUOTE_ALL)
            writer.writerows(rows)

    def csv_to_ts(self):
        for language in self.languages:
            ts_file = self._ts_file(language)

            # csv2po cannot handle partially quoted files
            self.sort_csv(
                ts_file.with_suffix(".csv"),
                ts_file.with_suffix(".csv"),
                sort_columns=["location", "source", "target"],
            )
            run_local(f"csv2po {ts_file.with_suffix('.csv')}  -o {ts_file.with_suffix('.po')}")
            run_local(f"po2ts {ts_file.with_suffix('.po')}  -o {ts_file}")
        self.delete_po_files()
        self.compile()

    def compile(self):
        run_local(f"/usr/lib/qt6/bin/lrelease   {' '.join(self.get_all_ts_files())}")

    def insert_chatgpt_translations(
        self,
    ):
        """
        Reads translations for each language from 'translation_file' and pastes them
        into corresponding CSV files under 'csv_files_directory'. Each CSV is
        assumed to have columns: location, source, target.

        This version handles partially filled CSV files (e.g., 'app_de_DE.csv') by only
        filling blank targets. It also:
        - Raises ValueError if we try to overwrite a non-empty target cell,
        - Raises ValueError if the number of translation lines for a language
            doesn't match the number of empty target cells in that CSV file.
        - Finds CSV files by searching for filenames that end with '_{lang}.csv'.
        """
        csv_files_directory = self.ts_folder
        translation_file = self.ts_folder / "chatgpt.txt"

        # --- STEP 1: Read and parse the translation file ---
        translations = {}
        current_lang = None
        current_lines: List[str] = []

        with open(translation_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n")
                if not line:
                    continue
                if line in self.languages:
                    # Store the previous language block if it exists
                    if current_lang is not None:
                        translations[current_lang] = current_lines  # type: ignore
                    current_lang = line
                    current_lines = []
                else:
                    # Collect translation lines for the current_lang
                    if current_lang is not None:
                        current_lines.append(line)

        # Store the final language block if any
        if current_lang is not None:
            translations[current_lang] = current_lines

        # --- STEP 2: For each language, find matching CSV and fill it ---
        for lang in self.languages:
            # We'll search for any file whose name ends with _{lang}.csv
            # For example, 'app_de_DE.csv' for lang='de_DE'
            pattern = f"*_{lang}.csv"
            matching_files = list(csv_files_directory.glob(pattern))

            if not matching_files:
                print(f"No CSV found for language {lang} matching pattern '{pattern}', skipping...")
                continue
            if len(matching_files) > 1:
                raise ValueError(
                    f"Ambiguous: found multiple CSVs for language '{lang}' matching pattern '{pattern}':\n"
                    f"{matching_files}\n"
                    "Please ensure there's exactly one matching CSV."
                )

            csv_path = matching_files[0]
            lang_lines = translations.get(lang, [])

            # Read all rows from the CSV
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Gather indices of rows where target is empty
            empty_target_indices = []
            for i, row in enumerate(rows):
                # If 'target' is already populated, we won't overwrite it, so just skip it.
                # We'll only fill blank targets.
                if not row["target"].strip():
                    empty_target_indices.append(i)

            # Check count
            if len(lang_lines) != len(empty_target_indices):
                raise ValueError(
                    f"For language '{lang}' in file '{csv_path.name}':\n"
                    f" - The CSV has {len(empty_target_indices)} empty targets.\n"
                    f" - The translation file has {len(lang_lines)} lines.\n"
                    "They must match to paste correctly."
                )

            # Fill the empty targets
            for i_empty, translation_line in zip(empty_target_indices, lang_lines):
                # Extra safety check: ensure no content was put in after we counted
                if rows[i_empty]["target"].strip():
                    raise ValueError(
                        f"Cannot overwrite target in '{csv_path.name}' at row {i_empty+1}. "
                        f"Existing value: '{rows[i_empty]['target']}'"
                    )
                rows[i_empty]["target"] = translation_line

            # Write updated rows back to CSV
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                fieldnames = ["location", "source", "target"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            print(f"Successfully pasted {len(lang_lines)} translations into '{csv_path}'")
