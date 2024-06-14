import copy
from typing import Any, Dict, List, Type, Union

import requests

JSONType = Union[Dict[str, Any], List[Any], int, str, float, bool, Type[None]]

keys_to_redact = [
    "hfToken",
    "token",
    "accessKey",
    "secretKey",
    "secret",
    "awsAccessKeyId",
    "awsSecretAccessKey",
    "image",
]


keys_to_redact = ["hfToken", "token", "accessKey", "secretKey", "secret", "awsAccessKeyId", "awsSecretAccessKey"]


def max_epochs_of_model_response(model: Dict):
    if "modelRun" in model and "renderedConfig" in model["modelRun"]:
        return model["modelRun"]["renderedConfig"]["trainer"]["epochs"]
    return None


def redact_dict(payload: Dict):
    def _redact_helper(config: Dict):
        for key in config:
            if isinstance(config[key], dict):
                config[key] = _redact_helper(config[key])
            elif key in keys_to_redact:
                config[key] = "<REDACTED>"
        return config

    return _redact_helper(copy.deepcopy(payload))


def _get_error(resp):
    try:
        data = resp.json()
        if data is None:
            return "Unknown server error"
        if "error" in data:
            return data["error"]
        return resp.reason
    except requests.exceptions.JSONDecodeError:
        return f"Failed to decode payload as JSON. Payload text: \n{resp.text}\n"
