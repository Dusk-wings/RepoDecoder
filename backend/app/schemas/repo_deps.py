from pydantic import BaseModel, ConfigDict


class FileDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    file_path: str


class RepoDependencies(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    version: str
    type: str
    language: str

    file: FileDetail
