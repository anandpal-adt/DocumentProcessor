from pydantic import AliasPath, BaseModel, Field


class Dataset(BaseModel):
    uuid: str
    name: str
    connection_type: str = Field(validation_alias=AliasPath("connection", "type"))
    connection_name: str = Field(validation_alias=AliasPath("connection", "name"))
    # TODO: re-enable these fields
    # columns: List[str]
    # num_rows: int = Field(validation_alias=AliasPath("datasetInfo", "datasetProfile",
    #    "DatasetProfile", "num_examples"))
    status: str
