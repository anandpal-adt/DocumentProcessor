import urllib.parse


def encode_url_param(param: str) -> str:
    # Encode url param to avoid issues with special characters
    return urllib.parse.quote(param, safe="")
