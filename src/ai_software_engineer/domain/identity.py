"""Canonical identifiers shared by domain boundaries.

Keeping these aliases in one module prevents a context, run, or project identifier
from silently acquiring different validation rules in different layers.
"""

from typing import Annotated

from pydantic import StringConstraints

ProjectId = Annotated[str, StringConstraints(pattern=r"^project_[a-z0-9][a-z0-9_-]{2,63}$")]
RunId = Annotated[str, StringConstraints(pattern=r"^run_[a-z0-9][a-z0-9_-]{2,63}$")]
ContextId = Annotated[str, StringConstraints(pattern=r"^ctx_[a-f0-9]{64}$")]

__all__ = ["ContextId", "ProjectId", "RunId"]
