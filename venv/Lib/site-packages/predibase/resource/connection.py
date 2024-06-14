from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd
from dataclasses_json import config, dataclass_json, LetterCase

from predibase.pql.api import ServerResponseError, Session
from predibase.resource.connection_object import ConnectionObject
from predibase.resource.connection_properties import ConnectionType
from predibase.resource.user import User
from predibase.util import log_info


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Connection:
    session: Session
    _id: str = field(metadata=config(field_name="id"))
    _name: str = field(metadata=config(field_name="name"))
    _connection_type: ConnectionType = field(metadata=config(field_name="type"))
    _user: Optional[User] = field(metadata=config(field_name="user"), default=None)

    def __repr__(self):
        return (
            f"Connection(id={self.id}, name={self.name}, connection_type={self.connection_type}, author={self.author})"
        )

    def _build_dataset_with_backref(self, resp):
        from predibase.resource.dataset import Dataset

        resp["connection"] = self
        return Dataset.from_dict({"session": self.session, **resp})

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def author(self):
        return self._user.username if self._user else None

    @property
    def connection_type(self):
        return self._connection_type

    """List datasets associated with connection"""

    def list_datasets(self, df: bool = False) -> List[dict]:
        resp = self.session.get_json(f"/connections/{self.id}?with_datasets=true")
        datasets = resp["datasets"]
        if df:
            return pd.DataFrame(datasets).drop(columns=["connection"])
        return [self._build_dataset_with_backref(x) for x in datasets]

    """
    List possible objects (files, tables, etc.) that can be imported as datasets
    For flat file credentials (S3, GCS, etc.) this will return an empty list
    """

    def list_objects(self, df: bool = False) -> List[str]:
        resp = self.session.get_json(f"/connections/{self.id}/schema")
        if df:
            return pd.DataFrame(resp["tables"])
        return [ConnectionObject.from_dict(x) for x in resp["tables"]]

    def get_dataset(
        self,
        dataset_name: Optional[str] = None,
        dataset_id: Optional[int] = None,
    ) -> "Dataset":  # noqa
        return get_dataset(self.session, dataset_name, self.name, dataset_id)

    def import_dataset(self, object_name: str, dataset_name: str, exists_ok: bool = False) -> "Dataset":  # noqa
        if not self.session.is_plan_expired():
            req = {
                "connectionID": self.id,
                # "createDatasetsNames": [DatasetNaming(object_name, dataset_name)]
                "createDatasetsNames": [{"objectName": object_name, "datasetName": dataset_name}],
            }

            try:
                resp = self.session.post_json("/datasets", req)
            except ServerResponseError as e:
                if exists_ok and e.code == 400:
                    log_info(f"Dataset {dataset_name} already exists. exists_ok=True, so ignoring.")
                    return self.get_dataset(dataset_name)
                else:
                    raise e

            # TODO(hungcs): don't wait for dataset but move dataset creation outside workflow to be synchronous
            endpoint = f"/datasets/name/{dataset_name}?connectionName={self.name}"
            resp = self.session.wait_for_dataset(endpoint, until_fully_connected=True)
            return self._build_dataset_with_backref(resp)
        else:
            raise PermissionError(
                "Connecting data is locked for expired plans. Contact us to upgrade.",
            )


def get_dataset(
    session: Session,
    dataset_name: Optional[str] = None,
    connection_name: Optional[str] = None,
    dataset_id: Optional[int] = None,
) -> "Dataset":  # noqa
    from predibase.resource_util import build_dataset

    if not (dataset_name or connection_name or dataset_id):
        raise ValueError("Must provide one of [dataset_name, dataset_name + connection_name, dataset_id]")
    if dataset_id:
        if dataset_name or connection_name:
            raise ValueError("Cannot provide both dataset_id and dataset_name/connection_name")
        endpoint = f"/datasets/{dataset_id}"
    else:
        if connection_name and not dataset_name:
            raise ValueError("Cannot provide connection_name without dataset_name")
        endpoint = f"/datasets/name/{dataset_name}"
    if connection_name:
        endpoint += "?connectionName=" + connection_name
    resp = session.get_json(endpoint)

    return build_dataset(resp, session)
