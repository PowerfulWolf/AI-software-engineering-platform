"""Bounded Swift Package verification commands, not a general Swift shell."""

from typing import Final

SWIFT_VERIFICATION_COMMANDS: Final[tuple[str, ...]] = (
    "swift --version",
    "swift build --disable-automatic-resolution --skip-update",
    "swift test --disable-automatic-resolution --skip-update",
)


def is_restricted_swift_command(arguments: tuple[str, ...]) -> bool:
    """Disallow path, credential, plugin, compiler and sandbox overrides.

    Only configuration, product and focused test selection may follow the fixed
    prefix. Current-worktree defaults retain the sandbox and resolution controls.
    A successful build/test does not constitute UI/accessibility evidence.
    """
    if arguments == ("swift", "--version"):
        return True
    if len(arguments) < 4 or arguments[:4] not in tuple(
        tuple(command.split()) for command in SWIFT_VERIFICATION_COMMANDS[1:]
    ):
        return False
    tail = arguments[4:]
    seen: set[str] = set()
    for index in range(0, len(tail), 2):
        if index + 1 == len(tail):
            return False
        option, value = tail[index : index + 2]
        if option == "-c":
            option = "--configuration"
        if option in seen or not value or value.startswith("-"):
            return False
        seen.add(option)
        if option == "--configuration":
            if value not in {"debug", "release"}:
                return False
        elif option == "--product" and arguments[1] == "build":
            if not all(character.isalnum() or character in "_-" for character in value):
                return False
        elif option == "--filter" and arguments[1] == "test":
            if len(value) > 256 or any(ord(character) < 32 for character in value):
                return False
        else:
            return False
    return True
