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


import json

import requests


def send_rpc_command(ip: str, port: str, username: str, password: str, method: str, params=None) -> str:
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
