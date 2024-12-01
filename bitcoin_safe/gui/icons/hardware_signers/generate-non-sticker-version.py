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


def replace_text_in_file(file_path, replacements):
    with open(file_path, "r", encoding="utf-8") as file:
        contents = file.read()

    # Perform all replacements specified in the replacements dictionary
    for old_word, new_word in replacements.items():
        contents = contents.replace(old_word, new_word)

    return contents


def process_files(directory, output_path, replacements):
    os.makedirs(output_path, exist_ok=True)
    # Loop through all files in the specified directory
    for filename in os.listdir(directory):
        if filename.endswith("-sticker.svg"):
            # Generate the new filename
            new_filename = filename.replace("-sticker.svg", ".svg")

            # Full path for the original and new files
            original_file_path = os.path.join(directory, filename)
            new_file_path = os.path.join(output_path, new_filename)

            # Replace text in the original file
            new_contents = replace_text_in_file(original_file_path, replacements)

            # Write the modified contents to the new file
            with open(new_file_path, "w", encoding="utf-8") as new_file:
                new_file.write(new_contents)
            print(f"Processed {filename} -> {new_filename}")


# Dictionary of words to replace
replacements = {'id="rect304"': 'visibility="hidden" id="rect304"', "Label": ""}

# Specify the directory containing your SVG files
directory_path = "."
output_path = "./generated"

process_files(directory_path, output_path, replacements)
