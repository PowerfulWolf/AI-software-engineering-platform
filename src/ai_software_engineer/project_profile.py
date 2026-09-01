"""Read-only, deterministic discovery of project-native engineering facts.

``ProjectProfile`` deliberately describes observations rather than interpreting
the project's rules.  The detector never invokes a project command, installs a
dependency, or writes to the target directory.  A later SpecCompiler may use
these facts to build a context and route an explicit conflict to a human.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from ai_software_engineer.domain.identity import ProjectId
from ai_software_engineer.domain.model import DomainModel, NonEmptyStr, ensure_unique
from ai_software_engineer.project_workspace import project_id_for_root

Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
ProjectRevision = Annotated[str, StringConstraints(pattern=r"^(unknown|[a-f0-9]{40,64})$")]
RelativePath = Annotated[str, StringConstraints(min_length=1, max_length=512)]
DetectorVersion = Annotated[str, StringConstraints(pattern=r"^t020-v[0-9]+$")]

DETECTOR_VERSION: Final[DetectorVersion] = "t020-v1"
UNKNOWN: Final[str] = "unknown"


class ProjectProfileError(RuntimeError):
    """Base error for fail-closed profile discovery."""


class ProjectProfileRootNotFound(ProjectProfileError):
    """Raised when the requested project root is not an existing directory."""


class ProjectProfilePathEscape(ProjectProfileError):
    """Raised when a discovered symlink would escape the project root."""


class ProjectProfileReadError(ProjectProfileError):
    """Raised when a required project fact cannot be read consistently."""


class ProjectProfileEncodingError(ProjectProfileError):
    """Raised when a native rule source is not valid UTF-8."""


class ProjectProfileMetadataError(ProjectProfileError):
    """Raised when project metadata contains contradictory VCS facts."""


class ProjectLanguage(StrEnum):
    """Languages intentionally supported by the v0.1 detector."""

    PYTHON = "python"
    JAVA = "java"
    GO = "go"
    TYPESCRIPT = "typescript"
    CPP = "cpp"
    UNKNOWN = "unknown"


class BuildSystem(StrEnum):
    """Build/package systems identified from declarative marker files."""

    PYTHON = "python"
    MAVEN = "maven"
    GRADLE = "gradle"
    GO = "go"
    NPM = "npm"
    PNPM = "pnpm"
    YARN = "yarn"
    BUN = "bun"
    CMAKE = "cmake"
    MESON = "meson"
    MAKE = "make"
    BAZEL = "bazel"
    UNKNOWN = "unknown"


class VcsKind(StrEnum):
    """Version-control marker observed at the project root."""

    GIT = "git"
    MERCURIAL = "mercurial"
    SUBVERSION = "subversion"
    BAZAAR = "bazaar"
    NONE = "none"
    UNKNOWN = "unknown"


class NativeRuleKind(StrEnum):
    """Project-native guidance source categories, not interpreted priorities."""

    AGENTS = "agents"
    CONTRIBUTING = "contributing"
    README = "readme"
    EDITORCONFIG = "editorconfig"
    CI = "ci"
    TRELLIS_SPEC = "trellis-spec"


class LanguageFact(DomainModel):
    """One language and the sorted relative markers that support it."""

    language: ProjectLanguage
    markers: tuple[RelativePath, ...] = ()

    @model_validator(mode="after")
    def validate_markers(self) -> Self:
        for marker in self.markers:
            _validate_relative_path(marker)
        ensure_unique(self.markers, "LanguageFact markers")
        if self.language is ProjectLanguage.UNKNOWN and self.markers:
            raise ValueError("unknown language cannot carry markers")
        if self.language is not ProjectLanguage.UNKNOWN and not self.markers:
            raise ValueError("known language requires at least one marker")
        return self


class BuildSystemFact(DomainModel):
    """One build system and the sorted relative marker files that support it."""

    system: BuildSystem
    markers: tuple[RelativePath, ...] = ()

    @model_validator(mode="after")
    def validate_markers(self) -> Self:
        for marker in self.markers:
            _validate_relative_path(marker)
        ensure_unique(self.markers, "BuildSystemFact markers")
        if self.system is BuildSystem.UNKNOWN and self.markers:
            raise ValueError("unknown build system cannot carry markers")
        if self.system is not BuildSystem.UNKNOWN and not self.markers:
            raise ValueError("known build system requires at least one marker")
        return self


class VcsInfo(DomainModel):
    """VCS marker and optional, locally readable revision/ref facts."""

    kind: VcsKind
    marker: RelativePath | None = None
    revision: ProjectRevision | None = None
    ref: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_vcs_shape(self) -> Self:
        if self.marker is not None:
            _validate_relative_path(self.marker)
        if self.kind is VcsKind.NONE:
            if self.marker is not None or self.revision is not None or self.ref is not None:
                raise ValueError("VcsInfo NONE cannot carry marker, revision, or ref")
        elif self.marker is None:
            raise ValueError("VcsInfo marker is required for a detected VCS")
        if self.kind is not VcsKind.GIT and (self.revision is not None or self.ref is not None):
            raise ValueError("only Git VcsInfo may carry revision/ref")
        if self.ref is not None and not self.ref.startswith("refs/"):
            raise ValueError("Git ref must use a refs/ name")
        return self


class NativeRuleSource(DomainModel):
    """A UTF-8 project-native rule source represented without absolute paths."""

    uri: NonEmptyStr
    relative_path: RelativePath
    kinds: Annotated[tuple[NativeRuleKind, ...], Field(min_length=1)]
    sha256: Sha256
    byte_length: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        _validate_relative_path(self.relative_path)
        # The profile id is intentionally not repeated in this model; discovery
        # validates the concrete URI before constructing the source.
        if not self.uri.startswith("project://") or "//" in self.uri.removeprefix("project://"):
            raise ValueError("NativeRuleSource uri must be a project-relative project:// URI")
        ensure_unique(self.kinds, "NativeRuleSource kinds")
        return self


class ProjectProfile(DomainModel):
    """Deterministic facts about one project root and its native guidance."""

    kind: Literal["project_profile"] = "project_profile"
    schema_version: Literal["v0.1"] = "v0.1"
    project_id: ProjectId
    project_root_uri: NonEmptyStr
    source_revision: ProjectRevision
    detector_version: DetectorVersion = DETECTOR_VERSION
    languages: Annotated[tuple[LanguageFact, ...], Field(min_length=1)]
    build_systems: Annotated[tuple[BuildSystemFact, ...], Field(min_length=1)]
    vcs: VcsInfo
    native_rules: tuple[NativeRuleSource, ...] = ()
    observed_at: AwareDatetime
    profile_sha256: Sha256

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if self.project_root_uri != f"project://{self.project_id}":
            raise ValueError("project_root_uri must be derived from project_id")
        ensure_unique((fact.language for fact in self.languages), "ProjectProfile languages")
        ensure_unique((fact.system for fact in self.build_systems), "ProjectProfile build systems")
        ensure_unique(
            (source.uri for source in self.native_rules),
            "ProjectProfile native rule URIs",
        )
        for source in self.native_rules:
            expected_uri = f"project://{self.project_id}/{source.relative_path}"
            if source.uri != expected_uri:
                raise ValueError("native rule URI must match project_id and relative_path")
        if self.source_revision != (self.vcs.revision or UNKNOWN):
            raise ValueError("source_revision must match detected VCS revision or unknown")
        return self

    @classmethod
    def discover(
        cls,
        project_root: str | Path,
        *,
        project_id: ProjectId | str | None = None,
        observed_at: datetime | None = None,
        revision: str | None = None,
    ) -> ProjectProfile:
        """Read a project root and return a typed, deterministic profile.

        ``revision`` is an optional operator-supplied expected revision.  It is
        checked against locally readable Git metadata; a mismatch is rejected
        instead of silently producing a profile for a different source state.
        """

        root = _canonical_root(project_root)
        selected_project_id = _select_project_id(root, project_id)
        files = tuple(_iter_project_files(root))
        vcs = _discover_vcs(root)
        if revision is not None:
            _validate_revision(revision)
            detected_revision = vcs.revision or UNKNOWN
            if detected_revision != revision:
                raise ProjectProfileMetadataError(
                    "expected project revision does not match locally readable VCS revision"
                )
        source_revision = vcs.revision or UNKNOWN
        languages = _discover_languages(root, files)
        build_systems = _discover_build_systems(root, files)
        native_rules = _discover_native_rules(root, files, selected_project_id)
        timestamp = observed_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

        base = {
            "project_id": selected_project_id,
            "project_root_uri": f"project://{selected_project_id}",
            "source_revision": source_revision,
            "detector_version": DETECTOR_VERSION,
            "languages": languages,
            "build_systems": build_systems,
            "vcs": vcs,
            "native_rules": native_rules,
            "observed_at": timestamp,
            "profile_sha256": "0" * 64,
        }
        # Constructing a temporary object validates all cross-field invariants;
        # its timestamp is then excluded from the identity digest.
        provisional = cls.model_validate(base)
        digest = _profile_digest(provisional)
        return provisional.model_copy(update={"profile_sha256": digest})

    def validate_integrity(self) -> None:
        """Fail closed if a persisted profile's content hash no longer matches."""

        if self.profile_sha256 != _profile_digest(self):
            raise ProjectProfileMetadataError(
                "ProjectProfile profile_sha256 does not match content"
            )


def discover_project_profile(
    project_root: str | Path,
    *,
    project_id: ProjectId | str | None = None,
    observed_at: datetime | None = None,
    revision: str | None = None,
) -> ProjectProfile:
    """Functional facade for callers that do not need the classmethod form."""

    return ProjectProfile.discover(
        project_root,
        project_id=project_id,
        observed_at=observed_at,
        revision=revision,
    )


def profile_digest(profile: ProjectProfile) -> Sha256:
    """Return the deterministic identity hash for a profile."""

    return _profile_digest(profile)


_IGNORED_DIRECTORIES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".bzr",
        ".venv",
        "venv",
        "node_modules",
        "vendor",
        "build",
        "dist",
        "target",
        ".tox",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)
_VCS_MARKERS: Final[tuple[tuple[str, VcsKind], ...]] = (
    (".git", VcsKind.GIT),
    (".hg", VcsKind.MERCURIAL),
    (".svn", VcsKind.SUBVERSION),
    (".bzr", VcsKind.BAZAAR),
)
_LANGUAGE_SUFFIXES: Final[Mapping[str, ProjectLanguage]] = {
    ".py": ProjectLanguage.PYTHON,
    ".java": ProjectLanguage.JAVA,
    ".go": ProjectLanguage.GO,
    ".ts": ProjectLanguage.TYPESCRIPT,
    ".tsx": ProjectLanguage.TYPESCRIPT,
    ".d.ts": ProjectLanguage.TYPESCRIPT,
    ".cpp": ProjectLanguage.CPP,
    ".cc": ProjectLanguage.CPP,
    ".cxx": ProjectLanguage.CPP,
    ".hpp": ProjectLanguage.CPP,
    ".hh": ProjectLanguage.CPP,
    ".hxx": ProjectLanguage.CPP,
}
_LANGUAGE_FILENAMES: Final[Mapping[str, ProjectLanguage]] = {
    "pyproject.toml": ProjectLanguage.PYTHON,
    "setup.py": ProjectLanguage.PYTHON,
    "setup.cfg": ProjectLanguage.PYTHON,
    "requirements.txt": ProjectLanguage.PYTHON,
    "pipfile": ProjectLanguage.PYTHON,
    "poetry.lock": ProjectLanguage.PYTHON,
    "uv.lock": ProjectLanguage.PYTHON,
    "pom.xml": ProjectLanguage.JAVA,
    "build.gradle": ProjectLanguage.JAVA,
    "build.gradle.kts": ProjectLanguage.JAVA,
    "go.mod": ProjectLanguage.GO,
    "go.work": ProjectLanguage.GO,
    "tsconfig.json": ProjectLanguage.TYPESCRIPT,
    "tsconfig.base.json": ProjectLanguage.TYPESCRIPT,
    "cmakelists.txt": ProjectLanguage.CPP,
    "meson.build": ProjectLanguage.CPP,
}
_BUILD_MARKERS: Final[Mapping[str, BuildSystem]] = {
    "pyproject.toml": BuildSystem.PYTHON,
    "setup.py": BuildSystem.PYTHON,
    "setup.cfg": BuildSystem.PYTHON,
    "requirements.txt": BuildSystem.PYTHON,
    "pipfile": BuildSystem.PYTHON,
    "poetry.lock": BuildSystem.PYTHON,
    "uv.lock": BuildSystem.PYTHON,
    "pom.xml": BuildSystem.MAVEN,
    "build.gradle": BuildSystem.GRADLE,
    "build.gradle.kts": BuildSystem.GRADLE,
    "gradlew": BuildSystem.GRADLE,
    "settings.gradle": BuildSystem.GRADLE,
    "settings.gradle.kts": BuildSystem.GRADLE,
    "go.mod": BuildSystem.GO,
    "go.work": BuildSystem.GO,
    "package.json": BuildSystem.NPM,
    "package-lock.json": BuildSystem.NPM,
    "pnpm-lock.yaml": BuildSystem.PNPM,
    "yarn.lock": BuildSystem.YARN,
    "bun.lock": BuildSystem.BUN,
    "bun.lockb": BuildSystem.BUN,
    "cmakelists.txt": BuildSystem.CMAKE,
    "meson.build": BuildSystem.MESON,
    "makefile": BuildSystem.MAKE,
    "gnumakefile": BuildSystem.MAKE,
    "configure.ac": BuildSystem.MAKE,
    "makefile.am": BuildSystem.MAKE,
    "workspace.bazel": BuildSystem.BAZEL,
    "module.bazel": BuildSystem.BAZEL,
    "build": BuildSystem.BAZEL,
    "build.bazel": BuildSystem.BAZEL,
    "workspace": BuildSystem.BAZEL,
    "meson.options": BuildSystem.MESON,
    "xmake.lua": BuildSystem.MAKE,
}
_REVISION_PATTERN = re.compile(r"^[a-f0-9]{40,64}$")
_REF_PATTERN = re.compile(r"^refs/[A-Za-z0-9._/-]+$")


def _validate_relative_path(value: str) -> None:
    """Reject absolute/control/traversal paths after Pydantic's simple regex."""

    if value.startswith("/") or any(ord(character) < 32 for character in value):
        raise ValueError("relative path must be relative and contain no controls")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("relative path cannot contain empty or traversal segments")


def _canonical_root(project_root: str | Path) -> Path:
    candidate = Path(project_root).expanduser().resolve(strict=False)
    if not candidate.is_dir():
        raise ProjectProfileRootNotFound(str(candidate))
    return candidate


def _select_project_id(root: Path, project_id: ProjectId | str | None) -> ProjectId:
    if project_id is None:
        return project_id_for_root(root)
    try:
        from pydantic import TypeAdapter, ValidationError

        return TypeAdapter(ProjectId).validate_python(project_id)
    except ValidationError as error:
        raise ProjectProfileMetadataError(f"invalid project ID: {project_id!r}") from error


def _iter_project_files(root: Path) -> Iterator[Path]:
    """Yield regular files in stable order without following symlink directories."""

    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda path: path.name)
        except OSError as error:
            raise ProjectProfileReadError(
                f"cannot read project directory: {current.name}"
            ) from error
        directories: list[Path] = []
        for entry in entries:
            if entry.is_symlink():
                _ensure_contained(root, entry)
                continue
            try:
                is_directory = entry.is_dir()
                is_file = entry.is_file()
            except OSError as error:
                raise ProjectProfileReadError(
                    f"cannot inspect project entry: {entry.relative_to(root).as_posix()}"
                ) from error
            if is_directory:
                if entry.name not in _IGNORED_DIRECTORIES:
                    directories.append(entry)
            elif is_file:
                yield entry
        pending.extend(reversed(directories))


def _ensure_contained(root: Path, path: Path) -> None:
    try:
        resolved = path.resolve(strict=False)
    except OSError as error:
        raise ProjectProfilePathEscape(
            f"cannot resolve discovered symlink: {path.relative_to(root).as_posix()}"
        ) from error
    if not resolved.is_relative_to(root):
        raise ProjectProfilePathEscape(
            f"discovered symlink escapes project root: {path.relative_to(root).as_posix()}"
        )


def _discover_languages(root: Path, files: Iterable[Path]) -> tuple[LanguageFact, ...]:
    markers: dict[ProjectLanguage, set[str]] = defaultdict(set)
    for path in files:
        relative = path.relative_to(root).as_posix()
        lower_name = path.name.lower()
        language = _LANGUAGE_FILENAMES.get(lower_name)
        if language is not None:
            markers[language].add(relative)
        for suffix, suffix_language in _LANGUAGE_SUFFIXES.items():
            if lower_name.endswith(suffix):
                markers[suffix_language].add(relative)
                break
    if not markers:
        return (LanguageFact(language=ProjectLanguage.UNKNOWN),)
    return tuple(
        LanguageFact(language=language, markers=tuple(sorted(paths)))
        for language, paths in sorted(markers.items(), key=lambda item: item[0].value)
    )


def _discover_build_systems(root: Path, files: Iterable[Path]) -> tuple[BuildSystemFact, ...]:
    markers: dict[BuildSystem, set[str]] = defaultdict(set)
    for path in files:
        system = _BUILD_MARKERS.get(path.name.lower())
        if system is not None:
            markers[system].add(path.relative_to(root).as_posix())
    if not markers:
        return (BuildSystemFact(system=BuildSystem.UNKNOWN),)
    return tuple(
        BuildSystemFact(system=system, markers=tuple(sorted(paths)))
        for system, paths in sorted(markers.items(), key=lambda item: item[0].value)
    )


def _discover_vcs(root: Path) -> VcsInfo:
    markers: list[tuple[Path, VcsKind]] = []
    for marker_name, kind in _VCS_MARKERS:
        candidate = root / marker_name
        if candidate.is_symlink():
            _ensure_contained(root, candidate)
        if candidate.exists():
            markers.append((candidate, kind))
    if len(markers) > 1:
        raise ProjectProfileMetadataError("multiple VCS markers found at project root")
    if not markers:
        return VcsInfo(kind=VcsKind.NONE)
    marker, kind = markers[0]
    relative_marker = marker.relative_to(root).as_posix()
    if kind is not VcsKind.GIT:
        return VcsInfo(kind=kind, marker=relative_marker)
    if marker.is_file():
        # Git worktrees store a pointer to an external gitdir.  Reading that
        # external location would violate the target-root read boundary, so the
        # revision remains explicit unknown until a Git adapter supplies it.
        return VcsInfo(kind=VcsKind.GIT, marker=relative_marker)
    return _read_git_info(root, marker, relative_marker)


def _read_git_info(root: Path, git_dir: Path, marker: str) -> VcsInfo:
    head_path = git_dir / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise ProjectProfileReadError("cannot read Git HEAD metadata") from error
    if not head:
        raise ProjectProfileMetadataError("Git HEAD metadata is empty")
    if head.startswith("ref: "):
        ref = head.removeprefix("ref: ").strip()
        if not _REF_PATTERN.fullmatch(ref):
            raise ProjectProfileMetadataError("Git HEAD contains an invalid ref")
        ref_path = git_dir / ref
        revision: str | None = None
        try:
            if ref_path.is_file():
                revision = ref_path.read_text(encoding="ascii").strip()
            else:
                packed_refs = git_dir / "packed-refs"
                if packed_refs.is_file():
                    for line in packed_refs.read_text(encoding="ascii").splitlines():
                        if line and not line.startswith(("#", "^")):
                            candidate_ref, _, candidate_revision = line.partition(" ")
                            if candidate_ref == ref:
                                revision = candidate_revision.strip()
                                break
        except (OSError, UnicodeError) as error:
            raise ProjectProfileReadError("cannot read Git ref metadata") from error
        if revision is not None and not _REVISION_PATTERN.fullmatch(revision):
            raise ProjectProfileMetadataError("Git ref contains an invalid revision")
        return VcsInfo(kind=VcsKind.GIT, marker=marker, revision=revision, ref=ref)
    if not _REVISION_PATTERN.fullmatch(head):
        raise ProjectProfileMetadataError("Git HEAD contains neither a valid ref nor revision")
    return VcsInfo(kind=VcsKind.GIT, marker=marker, revision=head)


def _discover_native_rules(
    root: Path, files: Iterable[Path], project_id: ProjectId
) -> tuple[NativeRuleSource, ...]:
    kinds_by_path: dict[str, set[NativeRuleKind]] = defaultdict(set)
    paths = tuple(files)
    for path in paths:
        relative = path.relative_to(root).as_posix()
        name = path.name.lower()
        if name == "agents.md":
            kinds_by_path[relative].add(NativeRuleKind.AGENTS)
        if name.startswith("contributing"):
            kinds_by_path[relative].add(NativeRuleKind.CONTRIBUTING)
        if name.startswith("readme"):
            kinds_by_path[relative].add(NativeRuleKind.README)
        if name == ".editorconfig":
            kinds_by_path[relative].add(NativeRuleKind.EDITORCONFIG)
        if _is_ci_path(relative):
            kinds_by_path[relative].add(NativeRuleKind.CI)
        if relative == ".trellis/spec" or relative.startswith(".trellis/spec/"):
            kinds_by_path[relative].add(NativeRuleKind.TRELLIS_SPEC)
    sources: list[NativeRuleSource] = []
    for relative in sorted(kinds_by_path):
        path = root / relative
        try:
            content = path.read_bytes()
        except OSError as error:
            raise ProjectProfileReadError(f"cannot read native rule source: {relative}") from error
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProjectProfileEncodingError(
                f"native rule source is not valid UTF-8: {relative}"
            ) from error
        uri = f"project://{project_id}/{relative}"
        sources.append(
            NativeRuleSource(
                uri=uri,
                relative_path=relative,
                kinds=tuple(sorted(kinds_by_path[relative], key=lambda kind: kind.value)),
                sha256=hashlib.sha256(content).hexdigest(),
                byte_length=len(content),
            )
        )
    return tuple(sources)


def _is_ci_path(relative: str) -> bool:
    parts = relative.split("/")
    if len(parts) >= 3 and parts[0] == ".github" and parts[1] == "workflows":
        return True
    if relative in {".gitlab-ci.yml", ".gitlab-ci.yaml", "Jenkinsfile"}:
        return True
    if len(parts) >= 2 and parts[0] in {".circleci", ".buildkite"}:
        return parts[1] in {"config.yml", "config.yaml", "pipeline.yml", "pipeline.yaml"}
    return False


def _validate_revision(revision: str) -> None:
    if not _REVISION_PATTERN.fullmatch(revision):
        raise ProjectProfileMetadataError("revision must be a 40-64 character lowercase hex SHA")


def _profile_digest(profile: ProjectProfile) -> Sha256:
    payload = profile.model_dump(mode="json", exclude={"profile_sha256", "observed_at"})
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DETECTOR_VERSION",
    "UNKNOWN",
    "BuildSystem",
    "BuildSystemFact",
    "DetectorVersion",
    "LanguageFact",
    "NativeRuleKind",
    "NativeRuleSource",
    "ProjectLanguage",
    "ProjectProfile",
    "ProjectProfileEncodingError",
    "ProjectProfileError",
    "ProjectProfileMetadataError",
    "ProjectProfilePathEscape",
    "ProjectProfileReadError",
    "ProjectProfileRootNotFound",
    "ProjectRevision",
    "RelativePath",
    "Sha256",
    "VcsInfo",
    "VcsKind",
    "discover_project_profile",
    "profile_digest",
]
