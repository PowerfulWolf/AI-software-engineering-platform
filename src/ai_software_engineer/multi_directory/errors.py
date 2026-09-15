"""Public failure contracts for multi-directory Requirement delivery."""


class RequirementSourceRevisionDrift(ValueError):
    """A Requirement cannot continue after one of its pinned Git revisions changes."""


__all__ = ["RequirementSourceRevisionDrift"]
