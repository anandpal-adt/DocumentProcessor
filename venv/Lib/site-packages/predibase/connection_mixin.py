from typing import List, Optional, Union

import pandas as pd

from predibase.pql.api import ServerResponseError
from predibase.resource.connection import Connection
from predibase.resource.connection_properties import (
    ADLSProperties,
    BigQueryProperties,
    ConnectionProperties,
    ConnectionType,
    DatabaseProperties,
    DatabricksProperties,
    GCSProperties,
    S3Properties,
    SnowflakeProperties,
)
from predibase.util import log_info


class ConnectionMixin:
    def list_connections(
        self,
        name: str = None,
        limit: int = 9999999,
        df: bool = False,
    ) -> Union[pd.DataFrame, List[Connection]]:
        """
        :param name: filter by connection name
        :param limit: max number of connections to return
        :param df: Whether to return pandas dataframe or list of objects
        :return: Pandas dataframe or list of connections
        """
        endpoint = f"/connections?limit={limit}"
        if name:
            endpoint += "&searchKeys[]=name&searchVals[]=" + name
        resp = self.session.get_json(endpoint)
        connections = [x for x in resp["connections"]]
        if df:
            return pd.DataFrame(connections)
        return [Connection.from_dict({"session": self.session, **c}) for c in connections]

    def create_connection(
        self,
        name: str,
        connection_type: ConnectionType,
        properties: ConnectionProperties,
        exists_ok: bool = False,
    ) -> Connection:
        if self.session.is_plan_expired():
            raise PermissionError(
                "Connecting data is locked for expired plans. Contact us to upgrade.",
            )

        conn_with_secret = {
            "connection": {
                "name": name,
                "type": connection_type.value,
            },
            "secret": {
                "secret": properties.to_dict(),
            },
        }

        try:
            resp = self.session.post_json("/connections", conn_with_secret)
            return Connection.from_dict({"session": self.session, **resp})
        except ServerResponseError as e:
            if exists_ok and e.code == 400:
                log_info(f"Connection {name} already exists. exists_ok=True, so ignoring.")
                return self.get_connection(name)
            else:
                raise e

    def create_connection_postgres(
        self,
        name: str,
        address: str,
        database: str,
        username: str,
        password: str,
        exists_ok: bool = False,
    ) -> Connection:
        properties = DatabaseProperties(address=address, database=database, username=username, password=password)
        return self.create_connection(name, ConnectionType.POSTGRESQL, properties, exists_ok)

    def create_connection_s3(self, name: str, key: str, secret: str, exists_ok: bool = False) -> Connection:
        """Create connection with Amazon S3 storage.

        :param name: Name of connection.
        :param key: Amazon access key ID.
        :param secret: Amazon secret access key.
        :param exists_ok: If True, ignore if connection already exists.
        :return: A new connection.
        """
        properties = S3Properties(key=key, secret=secret)
        return self.create_connection(name, ConnectionType.S3, properties, exists_ok)

    def create_connection_mysql(
        self,
        name: str,
        address: str,
        database: str,
        username: str,
        password: str,
        exists_ok: bool = False,
    ) -> Connection:
        properties = DatabaseProperties(address=address, database=database, username=username, password=password)
        return self.create_connection(name, ConnectionType.MYSQL, properties, exists_ok)

    def create_connection_redshift(
        self,
        name: str,
        address: str,
        database: str,
        username: str,
        password: str,
        exists_ok: bool = False,
    ) -> Connection:
        properties = DatabaseProperties(address=address, database=database, username=username, password=password)
        return self.create_connection(name, ConnectionType.REDSHIFT, properties, exists_ok)

    def create_connection_snowflake(
        self,
        name: str,
        user: str,
        password: str,
        account: str,
        database: str,
        warehouse: str,
        schema: str,
        exists_ok: bool = False,
    ) -> Connection:
        properties = SnowflakeProperties(
            user=user,
            password=password,
            account=account,
            database=database,
            warehouse=warehouse,
            schema=schema,
        )
        return self.create_connection(name, ConnectionType.SNOWFLAKE, properties, exists_ok)

    def create_connection_adls(
        self,
        name: str,
        account_key: str,
        connection_string: str,
        exists_ok: bool = False,
    ) -> Connection:
        properties = ADLSProperties(account_key=account_key, connection_string=connection_string)
        return self.create_connection(name, ConnectionType.ADLS, properties, exists_ok)

    def create_connection_gcs(self, name: str, token: str, exists_ok: bool = False) -> Connection:
        properties = GCSProperties(token=token)
        return self.create_connection(name, ConnectionType.GCS, properties, exists_ok)

    def create_connection_bigquery(
        self,
        name: str,
        project: str,
        dataset: str,
        token: str,
        exists_ok: bool = False,
    ) -> Connection:
        properties = BigQueryProperties(project=project, dataset=dataset, token=token)
        return self.create_connection(name, ConnectionType.BIGQUERY, properties, exists_ok)

    def create_connection_databricks(
        self,
        name: str,
        access_token: str,
        server_host_name: str,
        http_path: str,
        schema: str = None,
        exists_ok: bool = False,
    ) -> Connection:
        properties = DatabricksProperties(
            access_token=access_token,
            server_host_name=server_host_name,
            http_path=http_path,
            schema_name=schema,
        )
        return self.create_connection(name, ConnectionType.DATABRICKS, properties, exists_ok)

    def get_connection(self, connection_name: Optional[str] = None, connection_id: Optional[int] = None) -> Connection:
        if not (connection_name or connection_id):
            raise ValueError("Must provide either connection_name or connection_id")

        endpoint = f"/connections/name/{connection_name}" if connection_name else f"/connections/{connection_id}"
        resp = self.session.get_json(endpoint)
        return Connection.from_dict({"session": self.session, **resp})

    def delete_connection(self, connection_name: str = None, connection_id: int = None):
        if connection_name and connection_id:
            raise ValueError("Cannot provide both connection_name and connection_id")
        if not (connection_name or connection_id):
            raise ValueError("Must provide either connection_name or connection_id")

        if connection_id:
            return self.session.delete_json("/connections", {"id": connection_id})
        return self.session.delete_json(f"/connections/name/{connection_name}")
