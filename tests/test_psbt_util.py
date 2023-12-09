from bitcoin_safe.psbt_util import *
import bdkpython as bdk


def test_psbts():

    psbt_0_2of3 = bdk.PartiallySignedTransaction(
        "cHNidP8BAIkBAAAAATqahH4QTEKfxm6qlALcWC5h8D9bjKFoW0VRfm4auf4aAAAAAAD9////AvQBAAAAAAAAIgAgsCBsnrRoOkUsY175u3Fa6vNXXwsSNbf4mDWFFvXODJH0AQAAAAAAACIAIPVnTHBKqnziIq5ov/TvQ8nNJYQ1MakbfdY7VMXIJbnpR8EmAAABAH0BAAAAAYMWmPX/X+Jq1QzTenGMmtvdeaMYEKYf7Nli0gzb+7C0AAAAAAD9////AugDAAAAAAAAIgAgHWI4I8UK5PLP+DtAXdlRI8Sts/PIRh1ksMD6iKlk/r6/GgAAAAAAABYAFNiY7EiZrTSaq0ipS+jFKXBQep4ON8EmAAEBK+gDAAAAAAAAIgAgHWI4I8UK5PLP+DtAXdlRI8Sts/PIRh1ksMD6iKlk/r4BBWlSIQIyOXzeZut4A5aUyMNWJy0Opx5iGruvdPBowW71rVQ1piEDDuRS5miVqUzK3RnF0adROAfU5jFNecF4zZ5TPebcRUMhAxU1ObeArGZ6bGPcb/KWg98LPu3Jj5wzMr9mDNI31ta0U64iBgIyOXzeZut4A5aUyMNWJy0Opx5iGruvdPBowW71rVQ1phixB43FVAAAgAEAAIAAAACAAAAAABUAAAAiBgMO5FLmaJWpTMrdGcXRp1E4B9TmMU15wXjNnlM95txFQxjRua98VAAAgAEAAIAAAACAAAAAABUAAAAiBgMVNTm3gKxmemxj3G/yloPfCz7tyY+cMzK/ZgzSN9bWtBiBe43+VAAAgAEAAIAAAACAAAAAABUAAAAAAQFpUiECwFSVDN1wlaOC4Xh3Vz8f1Fe1R3C9BnOEctx14BcM/vAhAvWDA1HgThJW6S0Buq4+ribWkdx/+Mq1qsmRr4XPMC1BIQNmWAeip+z4mEdQsVP1K0vLgB/pAvW5A/Vf5wi3tfahM1OuIgICwFSVDN1wlaOC4Xh3Vz8f1Fe1R3C9BnOEctx14BcM/vAYgXuN/lQAAIABAACAAAAAgAEAAAAVAAAAIgIC9YMDUeBOElbpLQG6rj6uJtaR3H/4yrWqyZGvhc8wLUEYsQeNxVQAAIABAACAAAAAgAEAAAAVAAAAIgIDZlgHoqfs+JhHULFT9StLy4Af6QL1uQP1X+cIt7X2oTMY0bmvfFQAAIABAACAAAAAgAEAAAAVAAAAAAEBaVIhAibQDjOdARwmI9G/ZnarEd23QZ/bskSSk5pzTsSbppqXIQNVWIlGZfiE5uzg9WV4Kkn7P+sdkX4mXCalj4wWRNH1dCED5H+E6OnZns/lomlsiSKclAcFlG7AZROwRk/voGCezotTriICAibQDjOdARwmI9G/ZnarEd23QZ/bskSSk5pzTsSbppqXGLEHjcVUAACAAQAAgAAAAIAAAAAAFAAAACICA1VYiUZl+ITm7OD1ZXgqSfs/6x2RfiZcJqWPjBZE0fV0GNG5r3xUAACAAQAAgAAAAIAAAAAAFAAAACICA+R/hOjp2Z7P5aJpbIkinJQHBZRuwGUTsEZP76Bgns6LGIF7jf5UAACAAQAAgAAAAIAAAAAAFAAAAAA="
    )
    psbt_1_2of3 = bdk.PartiallySignedTransaction(
        "cHNidP8BAIkBAAAAATqahH4QTEKfxm6qlALcWC5h8D9bjKFoW0VRfm4auf4aAAAAAAD9////AlgCAAAAAAAAIgAgsCBsnrRoOkUsY175u3Fa6vNXXwsSNbf4mDWFFvXODJGQAQAAAAAAACIAIP0Ts8vJczsQLi1FvMD/RkcQMQqvjX5Uyh98yNm5KKhzR8EmAAABAH0BAAAAAYMWmPX/X+Jq1QzTenGMmtvdeaMYEKYf7Nli0gzb+7C0AAAAAAD9////AugDAAAAAAAAIgAgHWI4I8UK5PLP+DtAXdlRI8Sts/PIRh1ksMD6iKlk/r6/GgAAAAAAABYAFNiY7EiZrTSaq0ipS+jFKXBQep4ON8EmAAEBK+gDAAAAAAAAIgAgHWI4I8UK5PLP+DtAXdlRI8Sts/PIRh1ksMD6iKlk/r4iAgIyOXzeZut4A5aUyMNWJy0Opx5iGruvdPBowW71rVQ1pkcwRAIgKXaWbCmWs8FwBTQu67YBM3QShkYLE1Ag3LTyCJYp2FECIERAKtoA3GrLQED0QJn1N6E49FWMsQ+HRlbZ1UShmw9uAQEFaVIhAjI5fN5m63gDlpTIw1YnLQ6nHmIau6908GjBbvWtVDWmIQMO5FLmaJWpTMrdGcXRp1E4B9TmMU15wXjNnlM95txFQyEDFTU5t4CsZnpsY9xv8paD3ws+7cmPnDMyv2YM0jfW1rRTriIGAjI5fN5m63gDlpTIw1YnLQ6nHmIau6908GjBbvWtVDWmGLEHjcVUAACAAQAAgAAAAIAAAAAAFQAAACIGAw7kUuZolalMyt0ZxdGnUTgH1OYxTXnBeM2eUz3m3EVDGNG5r3xUAACAAQAAgAAAAIAAAAAAFQAAACIGAxU1ObeArGZ6bGPcb/KWg98LPu3Jj5wzMr9mDNI31ta0GIF7jf5UAACAAQAAgAAAAIAAAAAAFQAAAAABAWlSIQLAVJUM3XCVo4LheHdXPx/UV7VHcL0Gc4Ry3HXgFwz+8CEC9YMDUeBOElbpLQG6rj6uJtaR3H/4yrWqyZGvhc8wLUEhA2ZYB6Kn7PiYR1CxU/UrS8uAH+kC9bkD9V/nCLe19qEzU64iAgLAVJUM3XCVo4LheHdXPx/UV7VHcL0Gc4Ry3HXgFwz+8BiBe43+VAAAgAEAAIAAAACAAQAAABUAAAAiAgL1gwNR4E4SVuktAbquPq4m1pHcf/jKtarJka+FzzAtQRixB43FVAAAgAEAAIAAAACAAQAAABUAAAAiAgNmWAeip+z4mEdQsVP1K0vLgB/pAvW5A/Vf5wi3tfahMxjRua98VAAAgAEAAIAAAACAAQAAABUAAAAAAQFpUiEDHmZf8lOi367yritD9OBEELdnlxBDQJ8RJ6K4XOLEj4chAzEeI4tAmDMbcRnTWKK8hLiBt0B4SGwxjNipmdepFuElIQM0k/Q5IHXpN2wyoRpv4qs0vvdDu1faStzIJdnmttWKJ1OuIgIDHmZf8lOi367yritD9OBEELdnlxBDQJ8RJ6K4XOLEj4cYsQeNxVQAAIABAACAAAAAgAAAAAASAAAAIgIDMR4ji0CYMxtxGdNYoryEuIG3QHhIbDGM2KmZ16kW4SUYgXuN/lQAAIABAACAAAAAgAAAAAASAAAAIgIDNJP0OSB16TdsMqEab+KrNL73Q7tX2krcyCXZ5rbViicY0bmvfFQAAIABAACAAAAAgAAAAAASAAAAAA=="
    )
    psbt_0_1of1 = bdk.PartiallySignedTransaction(
        "cHNidP8BAH0BAAAAAaQmHDnvyNh3SMhYOptNUIbCEqkDyPUodsbshbyX6CS0BAAAAAD9////Ag7sSgAAAAAAFgAUgoFgSJlKKMq7iF1ZDLpqI6LlmrNwCAAAAAAAACIAIMXCKrkjoq9gCSacmVRW8+0qcwFyVWLQ3BLW2+NXV2FvScEmAAABAP3JAgIAAAABGju6Rif4mlNuTLV/JJ8FQXSUgrCxyBJqlomo3JzHVQoDAAAAAP3///8VtRExAAAAAAAWABSUfKgf8Gx4DtgCPlIV6SsF+I8FIZ5+QAAAAAAAFgAU7G63L/EV40CsWrmOVQAOV65hBUvMCVgAAAAAABepFMGNsv6av40/TGJOBGcbAjdCre5Gh+vLVQAAAAAAFgAUtwEGAFOlSqg/RCd8YV68tofpCAp+9EoAAAAAABYAFFOV8HAr7QNkAxVeo9K3poeglnA+poFaAAAAAAAWABSdWbWW0ehRFZbmTDHeo4g0P5ir+5S1SQAAAAAAGXapFDSAYPDISc0pYwcDv4jwuVIGhivgiKxfMlsAAAAAABYAFEIk7/vegOj1pmzNuNZAT11h7WuBV15PAAAAAAAXqRQ78S6GgebV361WMM6M/QRcPT1yj4dZZVsAAAAAABYAFKhkrTqxWd91WXwYtGORcNKuFl6QRJtZAAAAAAAWABS5WAprwfREeKtY0GSWEWUH/1fToNp0OQAAAAAAFgAUwy6wUb6UAvQ1qSTOMqZYzQoW0eEm0RazCAAAABYAFA/anu1dQBUKkO9aT8fFgtqOMpdRIRpXAAAAAAAZdqkU8pU2T3qf52tAfiNHPGx3rbJs/lCIrFK6LwAAAAAAFgAUA/DGv8DpP5AFAuCXfnkkxhnqP5GZDDoAAAAAABYAFCWRr8XphrCCO12RgcBKBDeGPDKGUkBQAAAAAAAWABQ74FXbsmiaoQKI20bzjnQwADs4LZiAPQAAAAAAFgAUMPAzgfc+NEQL+pJORoRmTqOLYi8Ccj8AAAAAABl2qRSzACucy7pGjjmIKQcya8TrDbBsj4isjIZSAAAAAAAWABS4SLqL0rXvVQUFqtTwd4b+3SHJQds4TgAAAAAAFgAUb4/333FxheUn7aTLWs8VCpZiLBgMviYAAQEffvRKAAAAAAAWABRTlfBwK+0DZAMVXqPSt6aHoJZwPiIGA4jB53vBV2PnTemvac24lRGSIc3BRfE3+eKvQzuTVdyuGL1fmV1UAACAAQAAgAAAAIAAAAAAFQAAAAAiAgMyP6YEUOBpARAkuF3hRA4AztrQpJbZ02gSnyo9Jivz5Ri9X5ldVAAAgAEAAIAAAACAAQAAABgAAAAAAA=="
    )
    psbt_1_1of1 = bdk.PartiallySignedTransaction(
        "cHNidP8BAH0BAAAAAaQmHDnvyNh3SMhYOptNUIbCEqkDyPUodsbshbyX6CS0BAAAAAD9////ApbwSgAAAAAAFgAU2JjsSJmtNJqrSKlL6MUpcFB6ng7oAwAAAAAAACIAIB1iOCPFCuTyz/g7QF3ZUSPErbPzyEYdZLDA+oipZP6+KMEmAAABAP3JAgIAAAABGju6Rif4mlNuTLV/JJ8FQXSUgrCxyBJqlomo3JzHVQoDAAAAAP3///8VtRExAAAAAAAWABSUfKgf8Gx4DtgCPlIV6SsF+I8FIZ5+QAAAAAAAFgAU7G63L/EV40CsWrmOVQAOV65hBUvMCVgAAAAAABepFMGNsv6av40/TGJOBGcbAjdCre5Gh+vLVQAAAAAAFgAUtwEGAFOlSqg/RCd8YV68tofpCAp+9EoAAAAAABYAFFOV8HAr7QNkAxVeo9K3poeglnA+poFaAAAAAAAWABSdWbWW0ehRFZbmTDHeo4g0P5ir+5S1SQAAAAAAGXapFDSAYPDISc0pYwcDv4jwuVIGhivgiKxfMlsAAAAAABYAFEIk7/vegOj1pmzNuNZAT11h7WuBV15PAAAAAAAXqRQ78S6GgebV361WMM6M/QRcPT1yj4dZZVsAAAAAABYAFKhkrTqxWd91WXwYtGORcNKuFl6QRJtZAAAAAAAWABS5WAprwfREeKtY0GSWEWUH/1fToNp0OQAAAAAAFgAUwy6wUb6UAvQ1qSTOMqZYzQoW0eEm0RazCAAAABYAFA/anu1dQBUKkO9aT8fFgtqOMpdRIRpXAAAAAAAZdqkU8pU2T3qf52tAfiNHPGx3rbJs/lCIrFK6LwAAAAAAFgAUA/DGv8DpP5AFAuCXfnkkxhnqP5GZDDoAAAAAABYAFCWRr8XphrCCO12RgcBKBDeGPDKGUkBQAAAAAAAWABQ74FXbsmiaoQKI20bzjnQwADs4LZiAPQAAAAAAFgAUMPAzgfc+NEQL+pJORoRmTqOLYi8Ccj8AAAAAABl2qRSzACucy7pGjjmIKQcya8TrDbBsj4isjIZSAAAAAAAWABS4SLqL0rXvVQUFqtTwd4b+3SHJQds4TgAAAAAAFgAUb4/333FxheUn7aTLWs8VCpZiLBgMviYAAQEffvRKAAAAAAAWABRTlfBwK+0DZAMVXqPSt6aHoJZwPiIGA4jB53vBV2PnTemvac24lRGSIc3BRfE3+eKvQzuTVdyuGL1fmV1UAACAAQAAgAAAAIAAAAAAFQAAAAEHAAEIawJHMEQCIES4GSlpjaAzwcOwQcfwXrKUSatQ1EJGqPUfokLrpPOmAiBiQ4hOQWCs3RCYiSJFBrke9cDfOv3MWwfbLpBJTwiFIQEhA4jB53vBV2PnTemvac24lRGSIc3BRfE3+eKvQzuTVdyuACICAkhCjgk5sNSHM7qWEB5GBE1wOgzX8TgsX8WvQ29TKmwmGL1fmV1UAACAAQAAgAAAAIABAAAAFwAAAAAA"
    )

    assert psbt_simple_json(psbt_0_1of1) == {
        "inputs": [
            {
                "bip32_derivation": [
                    [
                        "0388c1e77bc15763e74de9af69cdb895119221cdc145f137f9e2af433b9355dcae",
                        ["bd5f995d", "m/84'/1'/0'/0/21"],
                    ]
                ],
                "m": 1,
                "n": 1,
                "public_keys": [
                    "0388c1e77bc15763e74de9af69cdb895119221cdc145f137f9e2af433b9355dcae"
                ],
                "summary": {
                    "0388c1e77bc15763e74de9af69cdb895119221cdc145f137f9e2af433b9355dcae": {
                        "partial_sigs": False,
                        "signature": False,
                    }
                },
            }
        ]
    }

    assert psbt_simple_json(psbt_1_1of1) == {
        "inputs": [
            {
                "bip32_derivation": [
                    [
                        "0388c1e77bc15763e74de9af69cdb895119221cdc145f137f9e2af433b9355dcae",
                        ["bd5f995d", "m/84'/1'/0'/0/21"],
                    ]
                ],
                "m": 1,
                "n": 1,
                "public_keys": [
                    "0388c1e77bc15763e74de9af69cdb895119221cdc145f137f9e2af433b9355dcae"
                ],
                "signature": "3044022044b81929698da033c1c3b041c7f05eb29449ab50d44246a8f51fa242eba4f3a602206243884e4160acdd109889224506b91ef5c0df3afdcc5b07db2e90494f088521010388c1e77bc15763e74de9af69cdb895119221cdc145f137f9e2af433b9355dcae",
                "summary": {
                    "0388c1e77bc15763e74de9af69cdb895119221cdc145f137f9e2af433b9355dcae": {
                        "partial_sigs": False,
                        "signature": True,
                    }
                },
            }
        ]
    }

    assert psbt_simple_json(psbt_0_2of3) == {
        "inputs": [
            {
                "bip32_derivation": [
                    [
                        "0232397cde66eb78039694c8c356272d0ea71e621abbaf74f068c16ef5ad5435a6",
                        ["b1078dc5", "m/84'/1'/0'/0/21"],
                    ],
                    [
                        "030ee452e66895a94ccadd19c5d1a7513807d4e6314d79c178cd9e533de6dc4543",
                        ["d1b9af7c", "m/84'/1'/0'/0/21"],
                    ],
                    [
                        "03153539b780ac667a6c63dc6ff29683df0b3eedc98f9c3332bf660cd237d6d6b4",
                        ["817b8dfe", "m/84'/1'/0'/0/21"],
                    ],
                ],
                "m": 2,
                "n": 3,
                "public_keys": [
                    "0232397cde66eb78039694c8c356272d0ea71e621abbaf74f068c16ef5ad5435a6",
                    "030ee452e66895a94ccadd19c5d1a7513807d4e6314d79c178cd9e533de6dc4543",
                    "03153539b780ac667a6c63dc6ff29683df0b3eedc98f9c3332bf660cd237d6d6b4",
                ],
                "summary": {
                    "0232397cde66eb78039694c8c356272d0ea71e621abbaf74f068c16ef5ad5435a6": {
                        "partial_sigs": False,
                        "signature": False,
                    },
                    "030ee452e66895a94ccadd19c5d1a7513807d4e6314d79c178cd9e533de6dc4543": {
                        "partial_sigs": False,
                        "signature": False,
                    },
                    "03153539b780ac667a6c63dc6ff29683df0b3eedc98f9c3332bf660cd237d6d6b4": {
                        "partial_sigs": False,
                        "signature": False,
                    },
                },
            }
        ]
    }

    assert psbt_simple_json(psbt_1_2of3) == {
        "inputs": [
            {
                "bip32_derivation": [
                    [
                        "0232397cde66eb78039694c8c356272d0ea71e621abbaf74f068c16ef5ad5435a6",
                        ["b1078dc5", "m/84'/1'/0'/0/21"],
                    ],
                    [
                        "030ee452e66895a94ccadd19c5d1a7513807d4e6314d79c178cd9e533de6dc4543",
                        ["d1b9af7c", "m/84'/1'/0'/0/21"],
                    ],
                    [
                        "03153539b780ac667a6c63dc6ff29683df0b3eedc98f9c3332bf660cd237d6d6b4",
                        ["817b8dfe", "m/84'/1'/0'/0/21"],
                    ],
                ],
                "m": 2,
                "n": 3,
                "public_keys": [
                    "0232397cde66eb78039694c8c356272d0ea71e621abbaf74f068c16ef5ad5435a6",
                    "030ee452e66895a94ccadd19c5d1a7513807d4e6314d79c178cd9e533de6dc4543",
                    "03153539b780ac667a6c63dc6ff29683df0b3eedc98f9c3332bf660cd237d6d6b4",
                ],
                "partial_sigs": {
                    "0232397cde66eb78039694c8c356272d0ea71e621abbaf74f068c16ef5ad5435a6": {
                        "sig": "304402202976966c2996b3c17005342eebb60133741286460b135020dcb4f2089629d851022044402ada00dc6acb4040f44099f537a138f4558cb10f874656d9d544a19b0f6e",
                        "hash_ty": "SIGHASH_ALL",
                    }
                },
                "summary": {
                    "0232397cde66eb78039694c8c356272d0ea71e621abbaf74f068c16ef5ad5435a6": {
                        "partial_sigs": True,
                        "signature": False,
                    },
                    "030ee452e66895a94ccadd19c5d1a7513807d4e6314d79c178cd9e533de6dc4543": {
                        "partial_sigs": False,
                        "signature": False,
                    },
                    "03153539b780ac667a6c63dc6ff29683df0b3eedc98f9c3332bf660cd237d6d6b4": {
                        "partial_sigs": False,
                        "signature": False,
                    },
                },
            }
        ]
    }
