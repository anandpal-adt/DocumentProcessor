import itertools
import mimetypes
import os
import tempfile
from typing import List, Optional, Union

import pandas as pd
import requests
from google.protobuf.json_format import MessageToJson
from predibase_api.artifacts.v1.artifacts_pb2 import (
    ARTIFACT_TYPE_DATASET,
    PresignedUrlForUploadRequest,
    PresignedUrlForUploadResponse,
    RegisterUploadedFileAsDatasetRequest,
)

from predibase.pql import Session
from predibase.pql.api import ServerResponseError
from predibase.resource.connection import get_dataset
from predibase.resource.dataset import Dataset


class DatasetMixin:
    session: Session

    def list_datasets(
        self,
        name: str = None,
        limit: int = 9999999,
        df: bool = False,
    ) -> Union[pd.DataFrame, List[Dataset]]:
        """
        :param name: filter by dataset name
        :param limit: max number of datasets to return
        :param df: Whether to return pandas dataframe or list of objects
        :return: Pandas dataframe or list of datasets
        """
        endpoint = f"/datasets?limit={limit}"
        if name:
            endpoint += "&searchKeys[]=name&searchVals[]=" + name
        resp = self.session.get_json(endpoint)
        datasets = [x for x in resp["datasets"]]
        if df:
            return pd.DataFrame(datasets).drop(columns=["connection"])
        from predibase.resource_util import build_dataset

        return [build_dataset(x, self.session) for x in datasets]

    def list_public_datasets(self) -> Union[pd.DataFrame]:
        """Function to list the public datasets available for import.

        Returns: Pandas dataframe of public datasets
        """

        # Get public datasets
        resp = self.session.get_json("/datasets/get_ludwig_datasets")
        datasets = [x["name"] for x in resp["datasets"]]
        tasks = [", ".join(set(x["tasks"])) for x in resp["datasets"]]

        # Get public datasets connection
        endpoint = "/connections?searchKeys[]=name&searchVals[]=public_datasets"
        resp = self.session.get_json(endpoint)
        connection_id = resp["connections"][0]["id"]

        # Get already imported datasets
        endpoint = f"/datasets?indexVals[]={connection_id}&indexKeys[]=connectionID&limit=100"
        resp = self.session.get_json(endpoint)
        imported_datasets = [True if x in [x["name"] for x in resp["datasets"]] else False for x in datasets]

        return pd.DataFrame({"Name": datasets, "Tasks": tasks, "Imported": imported_datasets})

    def get_dataset(
        self,
        dataset_name: Optional[str] = None,
        connection_name: Optional[str] = None,
        dataset_id: Optional[int] = None,
    ) -> Dataset:
        return get_dataset(self.session, dataset_name, connection_name, dataset_id)

    def delete_dataset(self, dataset_name: str, connection_name: Optional[str] = None):
        dataset = self.get_dataset(dataset_name=dataset_name, connection_name=connection_name)
        return self.session.delete_json(f"/datasets/{dataset.id}")

    def create_dataset_from_df(self, df: pd.DataFrame, name: str) -> Dataset:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, f"{name}.parquet")
            df.to_parquet(path)
            return self._upload_file(path, name)

    def upload_file(self, file_path: str, name: str) -> Dataset:
        return self._upload_file(file_path, name)

    def check_file_dataset_exists(self, name: str) -> bool:
        resp = self.session.head(f"/datasets/check_file_dataset_exists/{name}")

        if resp.status_code == 200:
            return False

        if resp.status_code == 400:
            return True

        raise ServerResponseError("Failed to check dataset name", resp.status_code)

    def upload_dataset(self, file_path: str, name: Optional[str] = None) -> Dataset:
        if name is None:
            # Autogenerate a name
            name = os.path.basename(file_path).split(".")[0]
            for i in itertools.count(start=1):
                try:
                    exists = self.check_file_dataset_exists(name)
                except ServerResponseError:
                    exists = False

                if not exists:
                    break

                name = f"{name}_{i}"

            print(f"Dataset name was not explicitly provided. Defaulting to: {name}")

        print("Uploading dataset...")
        res = self._upload_file(file_path, name)
        print("Dataset uploaded.")
        return res

    def _upload_file(self, file_path: str, name: str) -> Dataset:
        if not self.session.is_plan_expired():
            with open(file_path, "rb") as f:
                file_name = os.path.basename(file_path)
                mime_type = mimetypes.guess_type(file_path)[0] or "text/plain"

                # Get presigned url for upload
                presigned_url_req = MessageToJson(
                    PresignedUrlForUploadRequest(
                        mime_type=mime_type,
                        expiry_seconds=3600,
                        artifact_type=ARTIFACT_TYPE_DATASET,
                    ),
                    preserving_proto_field_name=True,
                )
                resp = PresignedUrlForUploadResponse(
                    **self.session.post(
                        "/datasets/get_presigned_url",
                        data=presigned_url_req,
                    ),
                )

                # Unpack response data
                presigned_url = resp.url
                object_name = resp.object_name
                required_headers = resp.required_headers

                # Get required headers for presigned url upload
                headers = {"Content-Type": mime_type}
                for k, v in required_headers:
                    headers[k] = v

                # Upload file to blob storage with pre-signed url
                requests.put(presigned_url, data=f, headers=headers).raise_for_status()

                # Register uploaded file as dataset
                register_dataset_req = MessageToJson(
                    RegisterUploadedFileAsDatasetRequest(
                        dataset_name=name,
                        object_name=object_name,
                        file_name=file_name,
                    ),
                    preserving_proto_field_name=True,
                )
                resp = self.session.post("/datasets/register_uploaded_file", data=register_dataset_req)

                dataset_id = resp["id"]
                # TODO(hungcs): don't wait for dataset but move dataset creation outside workflow to be synchronous
                endpoint = f"/datasets/{dataset_id}"
                resp = self.session.wait_for_dataset(endpoint, until_fully_connected=True)

                from predibase.resource_util import build_dataset

                return build_dataset(resp, self.session)
        else:
            raise PermissionError(
                "Connecting data is locked for expired plans. Contact us to upgrade.",
            )

    def import_public_dataset(self, dataset_name: str) -> Dataset:
        """Function to import a public dataset.

        Args:
            dataset_name: Name of the public dataset to import

        Returns: Dataset
        """
        if not self.session.is_plan_expired():
            public_datasets = self.list_public_datasets()

            if public_datasets[public_datasets["Name"] == dataset_name]["Imported"].values[0]:
                raise Exception(f"Dataset {dataset_name} has already been imported.")

            data = {"selectedDataset": dataset_name}

            resp = self.session.post("/datasets/upload_ludwig_dataset", json=data)
            dataset_id = resp["id"]
            endpoint = f"/datasets/{dataset_id}"
            resp = self.session.wait_for_dataset(endpoint, until_fully_connected=True)

            from predibase.resource_util import build_dataset

            return build_dataset(resp, self.session)
        else:
            raise PermissionError(
                "Connecting data is locked for expired plans. Contact us to upgrade.",
            )
