from dataclasses import dataclass
from typing import List

import pandas as pd

from predibase.pql.api import Session


@dataclass
class FeatureMetadata:
    name: str
    datatype: str
    shape: List[int]


@dataclass
class ModelMetadata:
    name: str
    versions: List[str]
    platform: str
    inputs: List[FeatureMetadata]
    outputs: List[FeatureMetadata]

    @classmethod
    def from_dict(self, d):
        return ModelMetadata(
            name=d["name"],
            versions=d["versions"],
            platform=d["platform"],
            inputs=[FeatureMetadata(**md) for md in d["inputs"]],
            outputs=[FeatureMetadata(**md) for md in d["outputs"]],
        )


class Predictions:
    def __init__(self, model_outputs: List[FeatureMetadata], results: List):
        self.model_outputs = model_outputs
        self.results = results

    def to_pandas(
        self,
    ):
        """Convert the output data into pandas data frame."""
        from predibase.triton_util import get_output_data

        data_iterator = get_output_data(self.model_outputs, self.results)
        pred_df = pd.DataFrame(data_iterator).set_index("request_id")
        pred_df.index.rename(None, inplace=True)  # Clear the index name
        return pred_df


class Predictor:
    def __init__(
        self,
        session: Session,
        deployment_name: str,
        deployment_version: int = 0,
    ):
        # Set properties from constructor
        self.session = session
        self.deployment_name = deployment_name
        if deployment_version > 0:
            self.deployment_version = str(deployment_version)
        else:
            self.deployment_version = ""  # Empty string to get latest version
        self.grpc_endpoint = session.serving_grpc_endpoint
        self.http_endpoint = f"{self.session.serving_http_endpoint}/{session.tenant}/deployments"
        self.http_headers = {"Authorization": f"Bearer {self.session.token}"}

    def metadata(self) -> ModelMetadata:
        """Returns the model metadata for a given deployment name and optional version."""
        from predibase.triton_util import triton_metadata_http

        metadata = triton_metadata_http(
            endpoint=self.http_endpoint,
            model_name=self.deployment_name,
            model_version=self.deployment_version,
            headers=self.http_headers,
        )
        return ModelMetadata.from_dict(metadata)

    def predict(self, input_df: pd.DataFrame, stream=False) -> Predictions:
        """Returns predictions for an input dataframe.

        Set stream to true, to fetch results via secure grpc connection.
        """
        try:
            from predibase.triton_util import (
                get_data_iterator,
                get_grpc_creds,
                InferenceServerException,
                triton_predict_grpc_stream,
                triton_predict_http,
            )
        except ModuleNotFoundError:
            print("Predict not supported, please ensure you have installed predictor requirements:")
            print('pip install "predibase[predictor]"')
            return

        try:
            metadata = self.metadata()
        except InferenceServerException as e:
            print(f"Failed to get metadata: {e.message}")
            return

        # Get model inputs and outputs from metadata
        model_inputs = [(md.name, md.shape, md.datatype) for md in metadata.inputs]
        model_outputs = [md.name for md in metadata.outputs]

        # Get the data iterator using model metadata
        data_iterator = get_data_iterator(metadata, input_df)

        if stream:
            print(f"predict via gRPC stream: {self.grpc_endpoint}")
            try:
                # Use model name and version to query specific model
                model_name = metadata.name
                model_version = metadata.versions[0]
                grpc_headers = {
                    "tenant": self.session.tenant,
                    "model_name": model_name,
                    "model_version": str(model_version),
                }
                # Get grpc credentials
                grpc_creds = get_grpc_creds(self.session.token)
                results = triton_predict_grpc_stream(
                    endpoint=self.grpc_endpoint,
                    headers=grpc_headers,
                    creds=grpc_creds,
                    model_name=model_name,
                    model_version=model_version,
                    model_inputs=model_inputs,
                    data_iterator=data_iterator,
                )
            except Exception as e:
                print(f"error with stream predict -- {e}")
                stream = False  # fallback to http

        if not stream:
            print(f"predict via REST: {self.http_endpoint}")
            results = []
            for request_id, data in data_iterator:
                result = triton_predict_http(
                    endpoint=self.http_endpoint,
                    model_name=self.deployment_name,
                    model_version=str(self.deployment_version),
                    model_inputs=model_inputs,
                    model_outputs=model_outputs,
                    binary_data=False,
                    request_id=str(request_id),
                    headers=self.http_headers,
                    data_to_predict=data,
                )
                results.append((request_id, result))

        # Return a predictions object, which can lazyily load the predicions
        return Predictions(model_outputs, results)


class AsyncPredictor(Predictor):
    def __init__(
        self,
        session: Session,
        deployment_name: str,
        deployment_version: int = 0,
    ):
        super().__init__(session, deployment_name, deployment_version)

    async def metadata(self) -> ModelMetadata:
        """Returns the model metadata for a given deployment name and optional version."""
        from predibase.triton_util import triton_metadata_http_async

        metadata = await triton_metadata_http_async(
            endpoint=self.http_endpoint,
            model_name=self.deployment_name,
            model_version=self.deployment_version,
            headers=self.http_headers,
        )
        return ModelMetadata.from_dict(metadata)

    async def predict(self, input_df: pd.DataFrame, stream=False) -> Predictions:
        """Returns predictions for an input dataframe.

        Set stream to true, to fetch results via secure grpc connection.
        """
        try:
            from predibase.triton_util import (
                get_data_iterator,
                get_grpc_creds,
                triton_predict_grpc_stream_async,
                triton_predict_http_async,
            )
        except ModuleNotFoundError:
            print("Predict not supported, please ensure you have installed predictor requirements:")
            print('pip install "predibase[predictor]"')
            return

        metadata = await self.metadata()

        # Get model inputs and outputs from metadata
        model_inputs = [(md.name, md.shape, md.datatype) for md in metadata.inputs]
        model_outputs = [md.name for md in metadata.outputs]

        # Get the data iterator using model metadata
        data_iterator = get_data_iterator(metadata, input_df)

        if stream:
            print(f"predict via gRPC stream: {self.grpc_endpoint}")
            try:
                # Use model name and version to query specific model
                model_name = metadata.name
                model_version = metadata.versions[0]
                grpc_headers = {
                    "tenant": self.session.tenant,
                    "model_name": model_name,
                    "model_version": str(model_version),
                }
                # Get grpc credentials
                grpc_creds = get_grpc_creds(self.session.token)
                results = [
                    r
                    async for r in triton_predict_grpc_stream_async(
                        endpoint=self.grpc_endpoint,
                        headers=grpc_headers,
                        creds=grpc_creds,
                        model_name=model_name,
                        model_version=model_version,
                        model_inputs=model_inputs,
                        data_iterator=data_iterator,
                    )
                ]
            except Exception as e:
                print(f"error with stream predict -- {e}")
                stream = False  # fallback to http

        if not stream:
            print(f"predict via REST: {self.http_endpoint}")
            results = []
            for request_id, data in data_iterator:
                result = await triton_predict_http_async(
                    endpoint=self.http_endpoint,
                    model_name=self.deployment_name,
                    model_version=str(self.deployment_version),
                    model_inputs=model_inputs,
                    model_outputs=model_outputs,
                    binary_data=False,
                    request_id=str(request_id),
                    headers=self.http_headers,
                    data_to_predict=data,
                )
                results.append((request_id, result))

        # Return a predictions object, which can lazyily load the predicions
        return Predictions(model_outputs, results)
