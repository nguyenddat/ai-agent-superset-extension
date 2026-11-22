from pydantic import BaseModel, ConfigDict, Field


class CurrentUserOut(BaseModel):
    user_id: int
    username: str
    name: str
    is_admin: bool
    can_view: bool
    can_edit: bool
    can_query: bool
    can_review: bool


class RoleOptionOut(BaseModel):
    name: str
    description: str


class RoleAssignmentOut(BaseModel):
    user_id: int
    username: str
    name: str
    is_admin: bool
    roles: list[str]
    other_roles: list[str]


class RoleAssignmentsOut(BaseModel):
    roles: list[RoleOptionOut]
    users: list[RoleAssignmentOut]


class RoleAssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: list[str] = Field(max_length=10)


class UserRolesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_ids: list[int] = Field(max_length=100)


class UserRolesOut(BaseModel):
    user_id: int
    username: str
    role_ids: list[int]
    roles: list[str]
