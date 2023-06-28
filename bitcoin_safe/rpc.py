import requests
import json


def send_rpc_command(ip, port, username, password, method, params=None):
    """
    Sends an RPC command to a Bitcoin node.

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
    response = requests.post(
        url, headers=headers, data=payload, auth=(username, password)
    )

    # Return the response
    return response.json()
