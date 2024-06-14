from typing import Dict, List, Optional, Union

import pandas as pd

from predibase.pql.api import ServerResponseError
from predibase.resource.engine import DefaultEngineType, Engine
from predibase.util import log_info

SUPPORTED_SERVICE_TYPES = ["general", "serving"]


class EngineMixin:
    def create_engine(
        self,
        name,
        template: Optional[str] = None,
        template_id: Optional[int] = None,  # deprecated
        environment_id: Optional[int] = None,
        preload_model_path: Optional[str] = None,
        auto_suspend: int = 600,
        auto_resume: bool = True,
        exists_ok: bool = False,
    ) -> Engine:
        """
        :param auto_resume: whether the engine is allowed to automatically resume from a suspended state
            when given a job
        :param auto_suspend: how long the engine can be idle (have no active jobs) before resources are scaled down.
            Suspended engines take 8-10 minutes to start up again
        :param name: name of engine
        :param template: template name to use when creating the engine (see: get_engine_templates())
        :param template_id: template_id obtained from get_engine_templates() (DEPRECATED)
        :param environment_id: environment_id obtained from get_environments()
        :param preload_model_path: path to model to preload into the engine
        :param exists_ok: Do not raise an error and return the existing engine.
        :return: Engine
        """
        template_id = self._get_template_id(template) if template_id is None else template_id

        # TODO(geoffrey): should we make the user specify the service_type instead of inferring it here?
        service_type = self.get_engine_templates(full_info=True)[template_id]["serviceType"]
        if service_type == "serving":
            log_info("Creating engine of type 'serving'. Ignoring auto_suspend and auto_resume settings.")

        body = {
            "name": name,
            "templateID": template_id,
            "serviceType": service_type,
            "autoSuspendSeconds": auto_suspend,
            "autoResume": auto_resume,
        }
        if environment_id is not None:
            body["environmentID"] = environment_id
        if preload_model_path is not None:
            body["preloadModelPath"] = preload_model_path
        try:
            resp = self.session.post_json("/engines", body)
            return Engine.from_dict({"session": self.session, **resp})
        except ServerResponseError as e:
            if exists_ok and e.code == 400:
                log_info(f"Engine {name} already exists. exists_ok=True, so ignoring.")
                return self.get_engine(name)
            else:
                raise e

    def get_engine(
        self,
        name: Optional[str] = None,
        engine_id: Optional[int] = None,
        activate: Optional[bool] = False,
    ) -> Engine:
        if not (engine_id or name):
            raise ValueError("Must provide either engine_name or engine_id")
        if name and engine_id:
            raise ValueError("Cannot provide both engine name and engine_id")

        endpoint = f"/engines/{engine_id}" if engine_id else f"/engines/name/{name}"
        resp = self.session.get_json(endpoint)
        engine = Engine.from_dict({"session": self.session, **resp})
        if activate:
            try:
                engine.start()
            except Exception as e:
                print(f"Failed to start engine {name}: {e}")
        return engine

    def set_current_engine(
        self,
        name: Optional[str] = None,
        engine_id: Optional[int] = None,
        engine_type: DefaultEngineType = DefaultEngineType.QUERY,
    ):
        if engine_id and name:
            raise ValueError("Cannot provide both engine name and engine_id")
        if name:
            endpoint = f"/engines/current/name/{name}/{engine_type.value}"
            resp = self.session.put_json(endpoint, {})
        else:
            endpoint = f"/engines/current/{engine_type.value}"
            resp = self.session.put_json(endpoint, {"id": engine_id})
        return resp

    def get_current_engine(self, engine_type: DefaultEngineType = DefaultEngineType.QUERY):
        endpoint = "/engines/current"
        resp = self.session.get_json(endpoint)
        if engine_type.value not in resp:
            raise ValueError(f"Engine type {engine_type.value} not found in response: {resp.keys()}")
        return Engine.from_dict({"session": self.session, **resp[engine_type.value]})

    def list_engines(self, df: bool = False) -> Union[pd.DataFrame, List[Engine]]:
        """
        :param df: Whether to return pandas dataframe or list of objects
        :return: Pandas dataframe or list of engines
        """
        resp = self.session.get_json("/engines")
        engines = [x for x in resp["engines"]]
        if df:
            return pd.DataFrame(engines)
        return [Engine.from_dict({"session": self.session, **x}) for x in engines]

    def delete_engine(self, name: str):
        endpoint = f"/engines/name/{name}"
        resp = self.session.delete_json(endpoint)
        return resp

    def get_engine_templates(self, full_info: bool = False) -> Union[Dict[int, Dict[str, str]], Dict[int, Dict]]:
        """
        :param full_info: whether to return full info (with node labels, cpu, memory, storage, etc)
        :return: Dict of template_id -> template spec (i.e. "cpu-xsmall")
        """
        resp = self.session.get_json("/engines/schema")
        templates = resp["templates"]
        if full_info:
            return {x["id"]: x for x in templates}
        return {x["id"]: {"name": x["name"], "description": x["description"]} for x in templates}

    def get_engine_environments(self) -> Dict[int, Dict]:
        """
        :return: Dict of env UUID -> env spec (i.e. "cpu-xsmall")
        """
        resp = self.session.get_json("/environments/available")
        environments = resp["environments"]
        return {x["id"]: {"name": x["name"], "type": x["type"], "id": x["id"], "uuid": x["uuid"]} for x in environments}

    def _template_name_to_ids(self) -> Dict[str, int]:
        id_to_meta = self.get_engine_templates()
        return {meta["name"]: _id for _id, meta in id_to_meta.items()}

    def _get_template_id(self, name: str) -> int:
        if name is None:
            return 1
        name_to_ids = self._template_name_to_ids()
        if name not in name_to_ids:
            raise ValueError(
                f"Engine template name '{name}' not found. Available templates: {list(name_to_ids.keys())}",
            )
        return name_to_ids[name]
