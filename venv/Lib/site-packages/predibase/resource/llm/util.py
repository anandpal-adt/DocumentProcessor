from typing import Dict, List, Optional

from tabulate import tabulate


def print_events(events: Dict, print_header: Optional[bool] = True, existing_events: Optional[List] = []):
    compute_events = [(event["eventType"], event["timestamp"]) for event in events.get("ComputeEvents", [])]
    unique_new_events = [event for event in compute_events if event not in existing_events]
    if len(unique_new_events) > 0:
        if print_header:
            print(f"Resource Name: {events.get('name', '')}\n")
            headers = ["Event Type", "Timestamp", "Resource Active Time"]
            table = tabulate(unique_new_events, headers=headers, tablefmt="simple")
        else:
            table = tabulate(unique_new_events, tablefmt="simple")
        print(table)
    print(f"Resource Active Time (seconds): {events.get('resourceActiveTime', None)}", end="\r", flush=True)


def get_quantization_parameters(quantization_kwargs: Dict):
    """Validates and extracts parameters for quantization.

    `quantization_args` should either be None or be of the following format
    {
        "quantize": "some_quantization method",
        # "parameters" key is optional
        "parameters": [
            # we only allow exactly the following list of dictionaries or none at all.
            {"name": "GPTQ_BITS", "value": "4"},
            {"name": "GPTQ_GROUPSIZE", "value": "128"},
        ]
    }
    """
    environment_variables = None
    quantize = None
    if quantization_kwargs is not None:
        if not isinstance(quantization_kwargs, dict):
            raise ValueError("'quantization_kwargs' must be a dictionary.")
        if not all(key in ["quantize", "parameters"] for key in quantization_kwargs):
            raise ValueError("Only 'quantize' or 'parameters' are allowed as keys in 'quantization_kwargs'.")
        if "quantize" not in quantization_kwargs:
            raise ValueError("'quantize' must exist as a key in 'quantization_kwargs'.")
        quantize = quantization_kwargs["quantize"]
        if not isinstance(quantize, str):
            raise ValueError("'quantize' must be a string.")
        if "parameters" in quantization_kwargs:
            parameters = quantization_kwargs["parameters"]
            if not (isinstance(parameters, list) and parameters and len(parameters) == 2):
                raise ValueError(
                    "'parameters' must be provided as a non-empty list of the following format: "
                    "[{'name': 'GPTQ_BITS', 'value': 'some_value'}, "
                    "{'name': 'GPTQ_GROUPSIZE', 'value': 'some_other_value'}].",
                )
            for param in parameters:
                if not isinstance(param, dict):
                    raise ValueError("Each parameter must be a dictionary.")
                if len(param) != 2:
                    raise ValueError("You must provide two keys: 'name' and 'value'.")
                if "name" not in param or "value" not in param:
                    raise ValueError("You must provide two keys: 'name' and 'value'.")
                if param["name"] not in ["GPTQ_BITS", "GPTQ_GROUPSIZE"]:
                    raise ValueError(
                        "Only 'GPTQ_GROUPSIZE' and 'GPTQ_BITS' quantization parameters are allowed under 'name'.",
                    )
                param["value"] = str(param["value"])
                if not isinstance(param["value"], str):
                    raise ValueError(f"The value of {param['name']} must be a string.")
            environment_variables = parameters
    return quantize, environment_variables
