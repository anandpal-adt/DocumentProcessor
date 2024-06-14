from dataclasses import dataclass, field
from typing import Optional, Union

from dataclasses_json import config, dataclass_json, LetterCase


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Subscription:
    _id: int = field(metadata=config(field_name="id"))
    _tier: str = field(metadata=config(field_name="tier"))
    _is_trial: bool = field(metadata=config(field_name="isTrial"))
    _expiration: Union[str, None] = field(metadata=config(field_name="expiration"))
    _days_remaining_in_plan: Union[int, None] = field(metadata=config(field_name="daysRemainingInPlan"))
    _active: bool = field(metadata=config(field_name="active"))

    def __repr__(self):
        return (
            f"Subscription(id={self._id}, tier={self._tier}, is_trial={self._is_trial}, "
            f"expiration={self._expiration}, days_remaining_in_plan={self._days_remaining_in_plan}, "
            f"active={self._active})"
        )

    @property
    def id(self):
        return self._id

    @property
    def tier(self):
        return self._tier

    @property
    def is_trial(self):
        return self._is_trial

    @property
    def expiration(self):
        return self._expiration

    @property
    def days_remaining_in_plan(self):
        return self._days_remaining_in_plan

    @property
    def active(self):
        return self._active


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class Tenant:
    _name: str = field(metadata=config(field_name="name"))
    _short_code: str = field(metadata=config(field_name="shortCode"))
    _subscription: Subscription = field(metadata=config(field_name="subscription"))

    def __repr__(self):
        return f"Tenant(name={self._name}, short_code={self._short_code}, subscription={self._subscription})"

    @property
    def name(self):
        return self._name

    @property
    def short_code(self):
        return self._short_code

    @property
    def subscription(self):
        return self._subscription


@dataclass_json(letter_case=LetterCase.CAMEL)
@dataclass
class User:
    _id: int = field(metadata=config(field_name="id"))
    _username: str = field(metadata=config(field_name="username"))
    _uuid: str = field(metadata=config(field_name="uuid"))
    _tenant: Tenant = field(metadata=config(field_name="tenant"))
    _comment: Optional[str] = field(metadata=config(field_name="comment"), default=None)

    def __repr__(self):
        # Only return the username and uuid as relevant information
        return f"User(id={self._uuid}, username={self._username})"

    # Users should use the kratos UUID for RBAC
    @property
    def id(self):
        return self._uuid

    @property
    def user_id(self):
        return self._user_id

    @property
    def username(self):
        return self._username

    @property
    def tenant(self) -> Tenant:
        return self._tenant

    # def set_user_name(self, name: str):

    # def _update(self):
    #     resp = self.session.post_json("/users/update", self.__dict__())
