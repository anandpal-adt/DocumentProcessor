import enum
from abc import ABCMeta


class ConnectionType(enum.Enum):
    FILE = "file"
    PUBLIC_DATASETS = "public_datasets"
    ADLS = "adls"
    GCS = "gcs"
    S3 = "s3"
    MYSQL = "mysql"
    POSTGRESQL = "postgresql"
    SNOWFLAKE = "snowflake"
    REDSHIFT = "redshift"
    BIGQUERY = "bigquery"
    DATABRICKS = "databricks"


class ConnectionProperties(metaclass=ABCMeta):
    def __init__(self):
        pass

    def to_dict(self):
        return self.__dict__


class DatabaseProperties(ConnectionProperties):
    def __init__(self, address: str, database: str, username: str, password: str):
        self.address = address
        self.database = database
        self.username = username
        self.password = password


class SnowflakeProperties(ConnectionProperties):
    def __init__(
        self,
        user: str,
        password: str,
        account: str,
        database: str,
        warehouse: str,
        schema: str,
    ):
        self.user = user
        self.password = password
        self.account = account
        self.database = database
        self.warehouse = warehouse
        self.schema = schema


class S3Properties(ConnectionProperties):
    def __init__(self, key: str, secret: str):
        self.key = key
        self.secret = secret
        self.protocol = "s3"


class BigQueryProperties(ConnectionProperties):
    def __init__(self, project: str, dataset: str, token: str):
        self.project = project
        self.dataset = dataset
        self.token = token


class GCSProperties(ConnectionProperties):
    def __init__(self, token: str):
        self.protocol = "gcs"
        self.token = token


class ADLSProperties(ConnectionProperties):
    def to_dict(self):
        return {
            "accountKey": self.account_key,
            "connectionString": self.connection_string,
            "protocol": self.protocol,
        }

    def __init__(self, account_key: str, connection_string: str):
        self.account_key = account_key
        self.connection_string = connection_string
        self.protocol = "abfs"


class DatabricksProperties(ConnectionProperties):
    def __init__(self, access_token: str, server_host_name: str, http_path: str, schema_name: str = None):
        self.access_token = access_token
        self.server_host_name = server_host_name
        self.http_path = http_path
        self.schema_name = schema_name

    def to_dict(self):
        return {
            "serverHostname": self.server_host_name,
            "httpPath": self.http_path,
            "token": self.access_token,
            "schema": self.schema_name,
        }
