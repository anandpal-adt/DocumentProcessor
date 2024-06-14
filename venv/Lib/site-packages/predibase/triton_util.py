import os
import queue
import ssl
from functools import partial

import gevent.ssl as gssl
import numpy as np
import pandas as pd

# importing triton client libraries
import tritonclient.grpc as grpcclient
import tritonclient.grpc.aio as aio_grpcclient
import tritonclient.http as httpclient
import tritonclient.http.aio as aio_httpclient
from tritonclient.utils import InferenceServerException, triton_to_np_dtype

# import predibase predictor classes
from predibase.predictor import FeatureMetadata, ModelMetadata


def get_value(md: FeatureMetadata, row: pd.Series):
    """Returns the value as an array of 1 record, handling missing values."""
    col = md.name
    dt = md.datatype
    v = row[col]
    if dt == "BYTES":
        if row[col] is None:
            v = b""  # Default missing BYTES to empty string
        else:
            v = str(v).encode("utf-8")  # Cast any no-string to string
    elif row[col] is None:
        v = 0  # Default missing numbers to 0
    return np.array([v], dtype=triton_to_np_dtype(dt))


def get_input_data(metadata: ModelMetadata, row: pd.Series):
    """Create a ditionary for a row that matches the triton numpy format, encoding any strings."""
    d = {}
    for md in metadata.inputs:
        d[md.name] = get_value(md, row)
    return d


def get_data_iterator(metadata: ModelMetadata, df: pd.DataFrame):
    """Turns a pandas data frame into a data iterator with request_id=index, and single batch per row."""
    for i, row in df.iterrows():
        yield i, get_input_data(metadata, row)  # Return the index as its original type


def format_key(name):
    return name.replace("::", "_")


def get_output_data(model_outputs, results):
    for request_id, result in results:
        # If we hit an exception raise it immediately
        if isinstance(result, InferenceServerException):
            raise result
        d = {"request_id": request_id}
        for name in model_outputs:
            d[format_key(name)] = result.as_numpy(name)[0]  # Assume single result per record
        yield d


def triton_metadata_http(endpoint, model_name, headers, model_version=""):
    with httpclient.InferenceServerClient(
        endpoint,
        ssl=True,
        ssl_context_factory=gssl.create_default_context,
    ) as triton_client:
        return triton_client.get_model_metadata(model_name, model_version=model_version, headers=headers)


async def triton_metadata_http_async(endpoint, model_name, headers, model_version=""):
    async with aio_httpclient.InferenceServerClient(  # pylint: disable=unexpected-keyword-arg
        endpoint,
        ssl=True,
        ssl_context=ssl.create_default_context(),
    ) as triton_client:
        return await triton_client.get_model_metadata(model_name, model_version=model_version, headers=headers)


def triton_predict_http(
    endpoint,
    model_name,
    model_inputs,
    model_outputs,
    binary_data,
    headers,
    request_id,
    data_to_predict,
    model_version="",
):
    with httpclient.InferenceServerClient(
        endpoint,
        ssl=True,
        ssl_context_factory=gssl.create_default_context,
    ) as triton_client:  # pylint: disable=unexpected-keyword-arg
        # Define the http inputs
        inputs = [httpclient.InferInput(*params) for params in model_inputs]

        # Set input values
        for i, args in enumerate(model_inputs):
            d = data_to_predict[args[0]]
            inputs[i].set_data_from_numpy(d, binary_data=binary_data)

        # Define the http outputs
        outputs = [httpclient.InferRequestedOutput(name, binary_data=binary_data) for name in model_outputs]

        # Make inference
        return triton_client.infer(
            model_name,
            inputs,
            model_version=model_version,
            outputs=outputs,
            headers=headers,
            request_id=str(request_id),
        )


async def triton_predict_http_async(
    endpoint,
    model_name,
    model_inputs,
    model_outputs,
    binary_data,
    headers,
    request_id,
    data_to_predict,
    model_version="",
):
    async with aio_httpclient.InferenceServerClient(  # pylint: disable=unexpected-keyword-arg
        endpoint,
        ssl=True,
        ssl_context=ssl.create_default_context(),
    ) as triton_client:
        # Define the http inputs
        inputs = [aio_httpclient.InferInput(*params) for params in model_inputs]

        # Set input values
        for i, args in enumerate(model_inputs):
            d = data_to_predict[args[0]]
            inputs[i].set_data_from_numpy(d, binary_data=binary_data)

        # Define the http outputs
        outputs = [aio_httpclient.InferRequestedOutput(name, binary_data=binary_data) for name in model_outputs]

        # Make inference
        return await triton_client.infer(
            model_name,
            inputs,
            model_version=model_version,
            outputs=outputs,
            headers=headers,
            request_id=str(request_id),
        )


def triton_predict_grpc(
    endpoint,
    model_name,
    model_inputs,
    model_outputs,
    creds,
    headers,
    request_id,
    data_to_predict,
    model_version="",
):
    with grpcclient.InferenceServerClient(endpoint, creds=creds) as triton_client:
        # Define the grpc inputs
        inputs = [grpcclient.InferInput(*params) for params in model_inputs]

        # Set input values
        for i, args in enumerate(model_inputs):
            inputs[i].set_data_from_numpy(data_to_predict[args[0]])

        # Define the grpc outputs
        outputs = [grpcclient.InferRequestedOutput(name) for name in model_outputs]

        # Make inference
        return triton_client.infer(
            model_name,
            inputs,
            model_version=model_version,
            outputs=outputs,
            headers=headers,
            request_id=str(request_id),
        )


async def triton_predict_grpc_async(
    endpoint,
    model_name,
    model_inputs,
    model_outputs,
    creds,
    headers,
    request_id,
    data_to_predict,
    model_version="",
):
    async with aio_grpcclient.InferenceServerClient(endpoint, creds=creds) as triton_client:
        # Define the grpc inputs
        inputs = [aio_grpcclient.InferInput(*params) for params in model_inputs]

        # Set input values
        for i, args in enumerate(model_inputs):
            inputs[i].set_data_from_numpy(data_to_predict[args[0]])

        # Define the grpc outputs
        outputs = [aio_grpcclient.InferRequestedOutput(name) for name in model_outputs]

        # Make inference
        return await triton_client.infer(
            model_name,
            inputs,
            model_version=model_version,
            outputs=outputs,
            headers=headers,
            request_id=str(request_id),
        )


class UserData:
    def __init__(self):
        self._completed_requests = queue.Queue()


def callback(user_data, result, error):
    if error:
        user_data._completed_requests.put(error)
    else:
        user_data._completed_requests.put(result)


def get_grpc_creds(token: str):
    import grpc

    secure_cacert: str = os.getenv("CURL_CA_BUNDLE")
    if secure_cacert is not None:
        with open(secure_cacert, "rb") as fd:
            root_c = fd.read()
        scc = grpc.ssl_channel_credentials(root_certificates=root_c)
    else:
        scc = grpc.ssl_channel_credentials()
    tok = grpc.access_token_call_credentials(token)
    return grpc.composite_channel_credentials(scc, tok)


def triton_predict_grpc_stream(endpoint, model_name, model_inputs, creds, headers, data_iterator, model_version=""):
    """This function will iterate of the data iterator which is a tuple of (request_id, data_to_predict)"""
    user_data = UserData()

    with grpcclient.InferenceServerClient(endpoint, creds=creds) as triton_client:
        # Start stream registering callback
        triton_client.start_stream(callback=partial(callback, user_data), headers=headers)

        request_ids = []
        for request_id, data_to_predict in data_iterator:
            # Define the grpc inputs
            inputs = [grpcclient.InferInput(*params) for params in model_inputs]

            # Set input values
            for i, args in enumerate(model_inputs):
                inputs[i].set_data_from_numpy(data_to_predict[args[0]])

            # Make inference
            request_ids.append(request_id)
            triton_client.async_stream_infer(
                model_name=model_name,
                inputs=inputs,
                model_version=model_version,
                request_id=str(request_id),
            )

        # Return all results
        for request_id in request_ids:
            try:
                result = user_data._completed_requests.get()
                yield request_id, result
            except queue.Empty:
                break


async def async_stream_yield(data_iterator, model_name, model_version, model_inputs):
    for request_id, data_to_predict in data_iterator:
        # Define the grpc inputs
        inputs = [aio_grpcclient.InferInput(*params) for params in model_inputs]

        # Set input values
        for i, args in enumerate(model_inputs):
            inputs[i].set_data_from_numpy(data_to_predict[args[0]])

        # Issue the asynchronous sequence inference.
        yield {
            "model_name": model_name,
            "model_version": model_version,
            "inputs": inputs,
            "request_id": str(request_id),
        }


async def triton_predict_grpc_stream_async(
    endpoint,
    model_name,
    model_inputs,
    creds,
    headers,
    data_iterator,
    model_version="",
):
    """This function will iterate of the data iterator which is a tuple of (request_id, data_to_predict)"""
    async with aio_grpcclient.InferenceServerClient(endpoint, creds=creds) as triton_client:
        # Request iterator that yields the next request
        async def async_request_iterator():
            async for request in async_stream_yield(data_iterator, model_name, model_version, model_inputs):
                yield request

        # Start streaming
        response_iterator = triton_client.stream_infer(
            inputs_iterator=async_request_iterator(),
            headers=headers,
        )

        # Read response from the stream
        async for response in response_iterator:
            result, error = response
            if error:
                yield None, error
            else:
                request_id = result.get_response().id.split("_")[0]
                yield request_id, result
