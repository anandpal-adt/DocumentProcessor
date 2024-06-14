import enum

from predibase.resource.user import User


class PermissionNamespace(enum.Enum):
    DATASETS = "datasets"
    CONNECTIONS = "connections"

    ENGINES = "engines"
    MODELS = "models"


class PermissionRelation(enum.Enum):
    # General
    READ = "read"
    WRITE = "write"
    OWN = "own"

    # Engines
    USE = "read"


class PermissionSubjectType(enum.Enum):
    USER = "user"
    ROLE = "role"
    RESERVED_ROLE = "reserved role"


class PermissionRequest:
    def __init__(
        self,
        namespace: PermissionNamespace,
        data_id: int,
        subject_id: str = None,
        subject_name: str = None,
        subject_type: str = PermissionSubjectType,
        relation: str = PermissionRelation,
        is_revoke: bool = False,
    ):
        self.namespace = namespace
        self.data_id = data_id
        self.subject_id = subject_id
        self.subject_name = subject_name
        self.subject_type = subject_type
        self.relation = relation
        self.is_revoke = is_revoke

    def to_dict(self):
        return {
            "namespace": self.namespace.value,
            "dataID": self.data_id,
            "subjectID": self.subject_id,
            "subjectName": self.subject_name,
            "subjectType": self.subject_type.value,
            "relation": self.relation.value,
            "isRevoke": self.is_revoke,
        }


class PermissionMixin:
    def get_current_user(self) -> User:
        resp = self.session.get_json("/users/current")
        return User.from_dict({"session": self.session, **resp})

    def modify_resource_permission(
        self,
        namespace: PermissionNamespace,
        data_id: int,
        subject_id: str,
        subject_type: PermissionSubjectType,
        relation: PermissionRelation,
        is_revoke: bool = False,
    ):
        request = PermissionRequest(namespace, data_id, subject_id, None, subject_type, relation, is_revoke)
        self.session._post("/permissions/", json=request.to_dict())
        return True

    def check_requester_own(self, namespace: PermissionNamespace, data_id: int) -> bool:
        endpoint = f"/permissions/own?namespace={namespace.value}&dataID={data_id}"
        resp = self.session._get(endpoint)
        return resp

    def get_resource_permissions(self, namespace: PermissionNamespace, data_id: int):
        endpoint = f"/permissions?namespace={namespace.value}&dataID={data_id}"
        resp = self.session.get_json(endpoint)
        return resp
