from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from dataclasses_json import config, dataclass_json, LetterCase

from predibase.pql.api import Session
from predibase.predictor import AsyncPredictor, Predictor
from predibase.util import spinner


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Deployment:
    session: Session
    """['deployment_name', 'deployment_version', 'engine_name', 'model_name', 'model_version', 'deployment_url',
    'comment', 'error_text'],"""
    _name: int = field(metadata=config(field_name="name"))
    _deployment_version: int = field(metadata=config(field_name="deploymentVersion"))
    _engine_name: str = field(metadata=config(field_name="engineName"))
    _model_name: Optional[int] = field(metadata=config(field_name="modelName"))
    _model_version: Optional[int] = field(metadata=config(field_name="modelVersion"))
    _deployment_url: Optional[str] = field(metadata=config(field_name="deploymentUrl"))
    _comment: Optional[str] = field(metadata=config(field_name="comment"))
    _error_text: Optional[str] = field(metadata=config(field_name="errorText"))

    @spinner(name="Predict")
    def predict(self, input_df: pd.DataFrame, stream=False) -> pd.DataFrame:
        """Make predictions for each row of the pandas dataframe.

        :param input_df pandas DataFrame: Required input dataframe.
        :param bool stream: Optional flag to stream results via gRPC protocol (default False).
        :return: pandas dataframe with predictions.
        """
        if not self.session.tenant:
            raise Exception("tenant must be set on session before calling predict")
        predictor = Predictor(self.session, deployment_name=self._name, deployment_version=self._deployment_version)
        results = predictor.predict(input_df, stream)
        if results:
            return results.to_pandas()
        return pd.DataFrame()

    @spinner(name="Async Predict")
    async def async_predict(self, input_df: pd.DataFrame, stream=False) -> pd.DataFrame:
        """Make predictions for each row of the pandas dataframe.

        :param input_df pandas DataFrame: Required input dataframe.
        :param bool stream: Optional flag to stream results via gRPC protocol (default False).
        :return: pandas dataframe with predictions.
        """
        if not self.session.tenant:
            raise Exception("tenant must be set on session before calling predict")
        predictor = AsyncPredictor(
            self.session,
            deployment_name=self._name,
            deployment_version=self._deployment_version,
        )
        results = await predictor.predict(input_df, stream)
        if results:
            return results.to_pandas()
        return pd.DataFrame()

    def __repr__(self):
        return (
            f"Deployment(name={self.name}, deployment_version={self.deployment_version}, "
            f"engine_name={self.engine_name}, model_name={self.model_name}, "
            f"model_version={self.model_version}, deployment_url={self.deployment_url}, "
            f"comment='{self.comment}', error_text='{self.error_text}')"
        )

    @property
    def name(self):
        """Get name."""
        return self._name

    @property
    def deployment_version(self):
        """Get deployment version."""
        return self._deployment_version

    @property
    def engine_name(self):
        """Get engine name."""
        return self._engine_name

    @property
    def model_name(self):
        """Get model name."""
        return self._model_name

    @property
    def model_version(self):
        """Get model version."""
        return self._model_version

    @property
    def deployment_url(self):
        """Get deployment url."""
        return self._deployment_url

    @property
    def comment(self):
        return self._comment

    @property
    def error_text(self):
        return self._error_text

    def __dict__(self):
        return {
            "name": self.name,
            "deploymentVersion": self.deployment_version,
            "engineName": self.engine_name,
            "modelName": self.model_name,
            "modelVersion": self.model_version,
            "deploymentUrl": self.deployment_url,
            "comment": self.comment,
            "errorText": self.error_text,
        }
