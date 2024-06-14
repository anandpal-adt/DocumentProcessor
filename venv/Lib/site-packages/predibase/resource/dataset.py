from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

import pandas as pd
from dataclasses_json import config, dataclass_json, LetterCase

# from predibase.connection import Connection
# from predibase.model import Model
# import predibase
from predibase.pql.api import Session
from predibase.resource.connection import Connection

# if TYPE_CHECKING:  # Only imports the below statements during type checking
#     from predibase.resource.connection import Connection
#     from predibase.resource.model import Model
from predibase.resource.dataset_info import DatasetInfoWrapper
from predibase.resource.user import User


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class DataField:
    session: Session = field(metadata=config(exclude=True))
    id: int
    name: str
    dataset_id: int = field(metadata=config(field_name="datasetID"))
    _external_connection_id: Optional[int] = field(metadata=config(field_name="extConnectionID"), default=None)
    _external_connection: Optional[Connection] = field(metadata=config(field_name="extConnection"), default=None)

    def set_external_connection(self, ext_connection_id: int):
        self.session.post_json("/data/fields/connections/create", {"id": self.id, "extConnectionID": ext_connection_id})
        self._external_connection_id = ext_connection_id

    def remove_external_connection(self):
        if not self._external_connection_id:
            return

        self.session.post_json("/data/fields/connections/delete", {"id": self.id})
        self._external_connection_id = None
        self._external_connection = None

    @property
    def external_connection(self) -> Optional[Connection]:
        if not self._external_connection_id:
            return None

        if self._external_connection is not None:
            return self._external_connection

        endpoint = f"/connections/{self._external_connection_id}"
        resp = self.session.get_json(endpoint)
        ext_conn = Connection.from_dict({"session": self.session, **resp})
        self._external_connection = ext_conn
        return self._external_connection


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class DatasetNaming:
    object_name: str = field(metadata=config(field_name="objectName"))
    dataset_name: str = field(metadata=config(field_name="datasetName"))


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Dataset:
    session: Session = field(metadata=config(exclude=True))
    _id: str = field(metadata=config(field_name="id"))
    _uuid: str = field(metadata=config(field_name="uuid"))
    _name: str = field(metadata=config(field_name="name"))
    _object_name: str = field(metadata=config(field_name="objectName"))
    _created: str = field(metadata=config(field_name="created"))
    _updated: str = field(metadata=config(field_name="updated"))
    _connection_id: int = field(metadata=config(field_name="connectionID"))
    _dataset_info: Optional[DatasetInfoWrapper] = field(metadata=config(field_name="datasetInfo"), default=None)
    _dataset_profile: Optional[Dict] = field(metadata=config(field_name="datasetProfile"), default=None)
    _connection: Optional[Connection] = field(metadata=config(field_name="connection"), default=None)
    _user: Optional[User] = field(metadata=config(field_name="user"), default=None)

    def __repr__(self):
        return (
            f"Dataset(id={self.id}, name={self.name}, object_name={self.object_name}, "
            f"connection_id={self.connection_id}, author={self.author}, "
            f"created={self.created}, updated={self.updated})"
        )

    def _build_model_with_backref(self, resp):
        from predibase.resource_util import build_model

        resp["dataset"] = self
        return build_model(resp, self.session)

    @property
    def id(self):
        return self._id

    @property
    def uuid(self):
        return self._uuid

    @property
    def name(self):
        return self._name

    @property
    def row_count(self):
        if self.dataset_info:
            return self.dataset_info.info.row_count
        return None

    @property
    def size_bytes(self):
        if self.dataset_info:
            return self.dataset_info.info.size_bytes
        return None

    @property
    def author(self) -> str:
        return self._user.username if self._user else None

    @property
    def object_name(self):
        return self._object_name

    @property
    def connection_id(self):
        return self._connection_id

    @property
    def connection(self) -> Connection:
        if self._connection is not None:
            return self._connection
        connection = Connection.from_dict({"session": self.session, **self._get()["connection"]})
        self._connection = connection
        return connection

    @property
    def status(self) -> str:
        return self._get()["status"]

    @property
    def dataset_info(self) -> Optional[DatasetInfoWrapper]:
        if self._dataset_info is None:
            resp = self._get(with_dataset_info=True)
            if "datasetInfo" in resp:
                self._dataset_info = DatasetInfoWrapper.from_dict(resp["datasetInfo"])
        return self._dataset_info

    @property
    def dataset_profile(self):
        if self._dataset_profile is None:
            resp = self._get(with_dataset_info=True)
            if "datasetInfo" in resp and "datasetProfile" in resp["datasetInfo"]:
                self._dataset_profile = resp["datasetInfo"]["datasetProfile"]["DatasetProfile"]
        return self._dataset_profile

    @property
    def created(self):
        return self._created

    @property
    def updated(self):
        return self._updated

    def _get(self, with_dataset_info=False):
        resp = self.session.get_json(f"/datasets/{self.id}?withInfo={with_dataset_info}")
        return resp

    def list_models(self) -> List[dict]:
        resp = self.session.get_json(f"/datasets/{self.id}/models")
        dataset = resp["dataset"]
        return [
            self._build_model_with_backref(x["activeModel"]["model"]) for x in dataset["fields"] if "activeModel" in x
        ]

    def get_fields(self, df: bool = False) -> Union[pd.DataFrame, List[DataField]]:
        resp = self.session.get_json(f"/datasets/{self.id}/schema")

        fields = resp["fields"]
        field_data = {"Name": [], "Field_ID": []}

        for f in fields:
            field_data["Name"].append(f["name"])
            field_data["Field_ID"].append(f["id"])

        if df:
            return pd.DataFrame(field_data)

        return [DataField.from_dict({"session": self.session, **x}) for x in resp["fields"]]

    def to_dataframe(self, limit: int = 100000) -> pd.DataFrame:
        """This method converts a Predibase dataset to a pandas DataFrame. By default, it is limited to 100000 rows
        to prevent crashing due to OOM, however, the user can increase the limit if desired.

        Args: limit: Size of the DataFrame to return.

        Returns: pandas.DataFrame
        """
        query = f'SELECT * FROM "{self.name}" LIMIT {limit};'
        return self.session.execute(query, connection_id=self.connection_id)


class DatasetRef:
    def __init__(
        self,
        name: str,
        connection: Union[Connection, str],
        format_properties: Dict[str, str] = None,
    ):
        self.name = name
        self.connection = connection  # can either be a connection object or name
        self.format_properties = format_properties

    def __repr__(self):
        return f"""DatasetRef,
            name: {self.name},
            connection: {self.connection},
            format_properties: {self.format_properties}"""
