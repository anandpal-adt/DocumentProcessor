import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Union

from dataclasses_json import config, dataclass_json, LetterCase

from predibase.pql.api import Session


class DefaultEngineType(Enum):
    QUERY = "query"
    TRAIN = "train"


def get_replicas_str(node_dict: Dict) -> Union[str, None]:
    replicas = node_dict["replicas"]
    if replicas == node_dict["maxReplicas"] == 0:
        return None
    if node_dict["minReplicas"] != node_dict["maxReplicas"]:
        replicas = f"{replicas}x ({node_dict['minReplicas']} -> {node_dict['maxReplicas']})"
    return f"{replicas}x"


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class EngineTemplate:
    id: int
    name: str
    description: str
    service_type: str
    head_node_group: dict = field(metadata=config(field_name="headNodeGroup"))
    worker_node_groups: List[dict] = field(metadata=config(field_name="workerNodeGroups"))
    adaptive: bool = False
    disabled: bool = False
    suggested_workers: Optional[int] = field(default=0, metadata=config(field_name="suggestedWorkers"))
    max_workers: Optional[int] = field(default=0, metadata=config(field_name="maxWorkers"))

    def __str__(self):
        head = "Head: None"
        head_replicas = self.head_node_group["replicas"]

        if head_replicas != 0:
            cloud = next(iter(self.head_node_group["nodeType"]["clouds"]))
            cloud_engine_node_config = self.head_node_group["nodeType"]["clouds"][cloud]
            head_label = cloud_engine_node_config.get("publicLabel", cloud_engine_node_config["label"])
            head = f"Head: {get_replicas_str(self.head_node_group)} {head_label}"

        worker_title = "Workers:"
        workers = "\n".join(
            [
                f"- {get_replicas_str(worker)} {worker['nodeType']['name']}"
                for worker in self.worker_node_groups
                if get_replicas_str(worker) is not None
            ],
        )
        if workers.strip() == "":
            return head + "\nWorkers: None"
        return head + "\n" + worker_title + "\n" + workers


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Engine:
    session: Session
    _id: int = field(metadata=config(field_name="id"))
    _type: str = field(metadata=config(field_name="type"))
    _name: str = field(metadata=config(field_name="name"))
    _auto_suspend_seconds: Optional[int] = field(metadata=config(field_name="autoSuspendSeconds"))
    _template_id: int = field(metadata=config(field_name="templateID"))
    _environment_id: int = field(metadata=config(field_name="environmentID"))
    _service_type: str = field(metadata=config(field_name="serviceType"))
    _auto_resume: Optional[bool] = field(metadata=config(field_name="autoResume"), default=False)

    # _user: dict = field(metadata=config(field_name="user"))

    def __repr__(self):
        return (
            f"Engine(id={self.id}, name={self.name}, status={self.status}, type={self.type}, "
            f"service_type={self.service_type}, template_id={self.template_id}, environment_id={self.environment_id}, "
            f"auto_suspend_seconds={self.auto_suspend_seconds}, auto_resume={self.auto_resume})"
        )

    @property
    def id(self):
        return self._id

    @property
    def type(self):
        return self._type

    @property
    def service_type(self):
        return self._service_type

    @property
    def name(self):
        return self._name

    # @property
    # def author(self):
    #     if
    #     return self._user["username"]

    def set_name(self, value):
        self._name = value
        self._update()

    @property
    def auto_suspend_seconds(self):
        return self._auto_suspend_seconds

    def set_auto_suspend_seconds(self, value):
        self._auto_suspend_seconds = value
        self._update()

    @property
    def auto_resume(self):
        return self._auto_resume

    def set_auto_resume(self, value):
        self._auto_resume = value
        self._update()

    @property
    def instance_type_id(self):
        return self._instance_type_id

    @property
    def template_id(self):
        return self._template_id

    @property
    def environment_id(self):
        return self._environment_id

    def set_template_id(self, value):
        self._template_id = value
        self._update()

    def _get(self):
        return self.session.get_json(f"/engines/{self.id}")

    @property
    def status(self):
        return self._get()["engineStatus"]

    def __dict__(self):
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "autoSuspendSeconds": self.auto_suspend_seconds,
            "autoResume": self.auto_resume,
            "templateId": self.template_id,
            "environmentId": self.environment_id,
            "serviceType": self.service_type,
        }

    def _update(self):
        resp = self.session.put_json(f"/engines/{self.id}", self.__dict__())
        return resp

    def start(self):
        if not self.session.is_plan_expired():
            try:
                self.session.post_json("/engines/start", self.__dict__())
                resp = self.session.get_json_until(
                    f"/engines/{self.id}",
                    lambda resp: resp["engineStatus"] == "active",
                    lambda resp: "Engine failed to start with status ERRORED"
                    if resp["engineStatus"] == "errored"
                    else None,
                )
                return resp
            except RuntimeError:
                logging.info("Engine is already active")
        else:
            raise PermissionError(
                "Engines are locked for expired plans. Contact us to upgrade.",
            )

    def stop(self):
        try:
            self.session.post_json("/engines/stop", self.__dict__())
            resp = self.session.get_json_until(
                f"/engines/{self.id}",
                lambda resp: resp["engineStatus"] == "suspended",
                lambda resp: "Engine failed to start with status ERRORED"
                if resp["engineStatus"] == "errored"
                else None,
            )
            return resp
        except RuntimeError:
            logging.info("Engine is already suspended")
