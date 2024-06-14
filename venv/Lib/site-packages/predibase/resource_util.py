def build_dataset(resp, session):
    if "connection" in resp and resp["connection"] and isinstance(resp["connection"], dict):
        from predibase.resource.connection import Connection

        resp["connection"] = Connection.from_dict({"session": session, **resp["connection"]})
    from predibase.resource.dataset import Dataset

    return Dataset.from_dict({"session": session, **resp})


def build_model_repo(resp, session):
    if "dataset" in resp and resp["dataset"] and isinstance(resp["dataset"], dict):
        resp["dataset"] = build_dataset(resp["dataset"], session)
    from predibase.resource.model import ModelRepo

    return ModelRepo.from_dict({"session": session, **resp})


def build_engine(resp, session):
    from predibase.resource.engine import Engine

    return Engine.from_dict({"session": session, **resp})


def build_model(resp, session):
    if "dataset" in resp and resp["dataset"] and isinstance(resp["dataset"], dict):
        resp["dataset"] = build_dataset(resp["dataset"], session)
    if "repo" in resp and resp["repo"] and isinstance(resp["repo"], dict):
        resp["repo"] = build_model_repo(resp["repo"], session)
    if "engine" in resp and resp["engine"] and isinstance(resp["engine"], dict):
        resp["engine"] = build_engine(resp["engine"], session)
    from predibase.resource.model import Model

    return Model.from_dict({"session": session, **resp})
