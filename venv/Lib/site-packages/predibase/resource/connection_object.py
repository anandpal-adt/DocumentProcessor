from dataclasses import dataclass, field
from typing import List, Optional

from dataclasses_json import dataclass_json, LetterCase


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class DataField:
    name: str


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class ConnectionObject:
    """Represents an object in the connection that can be turned into a dataset."""

    name: str
    fields: Optional[List[DataField]] = field(default=None)

    def __repr__(self):
        s = self.name
        if self.fields is not None:
            s += " (" + ", ".join([f.name for f in self.fields]) + ")"
        return s
