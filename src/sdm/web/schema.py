"""The CLI's own argparse tree, as forms — and form values back into an argv.

The web UI has no list of commands or flags of its own. It reads them off
`cli.build_parser()`, so a flag added to a feature appears in its form with no
change here, and a form can never offer an option its command does not have.
Reading the tree means touching argparse's `_actions` and `_choices_actions`;
they are underscored, but they are how argparse's own help formatter reads a
parser, and nothing public exposes the same information.

The other direction is here too. Every argv is parsed by that same parser
before anything runs, so a bad value is refused with argparse's own message
instead of surfacing as a subprocess that exited 2.
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

#: Subcommands that are not offered as forms. `web` is this UI itself.
EXCLUDED_COMMANDS = frozenset({"web"})

#: Destinations the server sets on every run itself, so reports land where the
#: report browser reads them. Never offered in a form.
SERVER_OWNED = frozenset({"out_dir", "tmp_dir", "handler"})

#: What a value means where argparse cannot say: which boxes get a Browse button,
#: and for files, which extensions it lists. Keyed by `dest`, which is
#: consistent across features (`directory` is always a folder to read). A dest
#: missing here is a plain text box — never wrong, only less convenient.
#: Output paths are deliberately absent: a bare filename lands in
#: out/<feature>/, which is the common case and needs no picker.
PATH_HINTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "directory": ("dir", ()),
    "usb_path": ("dir", ()),
    "output_dir": ("dir", ()),
    "db_path": ("file", (".db",)),
    "fpcalc_path": ("file", ()),
    # A Spotify link or a CSV export; the box takes either, Browse finds the CSV.
    "playlist": ("file", (".csv",)),
}


class InvalidRequest(ValueError):
    """The form values do not make a valid command. The message is for the user."""


@dataclass(frozen=True)
class Invocation:
    command: str
    argv: list[str]   # starts with the command name; what `sdm` is passed
    display: str      # the same run as a line to paste into a terminal


def commands() -> list[dict]:
    """Every runnable command, with its fields, in the CLI's own order."""
    return list(_schema())


def build(command: str, values: Any) -> Invocation:
    """Turn submitted form values into a validated invocation of `command`.

    Values are keyed by `dest`. A flag is `true` to pass it. An option whose
    value is optional (`rekordbox --export-csv`) is `true` for the bare flag or a
    string for the flag with a value. Anything empty is left out, so argparse
    applies its own default rather than the UI restating it.
    """
    spec = next((c for c in _schema() if c["name"] == command), None)
    if spec is None:
        raise InvalidRequest(f"unknown command: {command}")
    if not isinstance(values, dict):
        raise InvalidRequest("values must be an object")

    options: list[str] = []
    positionals: list[str] = []
    for field in spec["fields"]:
        value = values.get(field["dest"])
        if field["positional"]:
            text = _text(field, value)
            if text:
                positionals.append(text)
            elif field["required"]:
                raise InvalidRequest(f"{field['label']} is required")
        elif field["kind"] == "flag":
            if value is True:
                options.append(field["flag"])
        elif field["kind"] == "optional_value":
            if value is True:
                options.append(field["flag"])
            elif _text(field, value):
                options += [field["flag"], _text(field, value)]
        else:
            text = _text(field, value)
            if text:
                options += [field["flag"], text]

    # `--` ends option parsing, so a positional that starts with "-" is still
    # read as a value. Always passed; shown only when it changes the meaning.
    argv = [command, *options, *(["--", *positionals] if positionals else [])]
    _validate(argv)

    needs_dashes = any(p.startswith("-") for p in positionals)
    shown = ["sdm", command, *options, *(["--"] if needs_dashes else []), *positionals]
    return Invocation(command=command, argv=argv, display=_join(shown))


# --- reading the parser ----------------------------------------------------


@lru_cache(maxsize=1)
def _schema() -> tuple[dict, ...]:
    from sdm import cli

    parser = cli.build_parser()
    action = _subparsers(parser)
    helps = {a.dest: a.help or "" for a in action._choices_actions}
    return tuple(
        {
            "name": name,
            "help": helps.get(name, ""),
            "description": sub.description or "",
            "fields": [f for f in (_field(a, sub.prog) for a in sub._actions) if f],
        }
        for name, sub in action.choices.items()
        if name not in EXCLUDED_COMMANDS
    )


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise RuntimeError("sdm's parser has no subcommands")


def _field(action: argparse.Action, prog: str) -> Optional[dict]:
    if isinstance(action, (argparse._HelpAction, argparse._VersionAction,
                           argparse._SubParsersAction)):
        return None
    if action.dest in SERVER_OWNED or action.help == argparse.SUPPRESS:
        return None

    positional = not action.option_strings
    if action.nargs == 0:
        kind = "flag"
    elif action.nargs == "?" and not positional:
        kind = "optional_value"
    elif action.choices:
        kind = "choice"
    elif action.type is int:
        kind = "integer"
    elif action.type is float:
        kind = "number"
    else:
        kind = "text"

    flag = max(action.option_strings, key=len) if action.option_strings else None
    path, accept = PATH_HINTS.get(action.dest, (None, ()))
    return {
        "dest": action.dest,
        "flag": flag,
        "label": flag or action.dest.replace("_", " "),
        "positional": positional,
        "kind": kind,
        "required": (positional and action.nargs not in ("?", "*")) or bool(action.required),
        # A flag's default is argparse's bookkeeping (store_false defaults to
        # True); the form's checkbox always means "pass this flag", off by default.
        "default": None if kind == "flag" else _jsonable(action.default),
        "help": _help(action, prog),
        "metavar": action.metavar if isinstance(action.metavar, str) else None,
        "choices": [str(c) for c in action.choices] if action.choices else None,
        "path": path,
        "accept": list(accept),
    }


def _help(action: argparse.Action, prog: str) -> str:
    """The help string with `%(default)s` and friends filled in, as `--help` shows it."""
    if not action.help:
        return ""
    params = dict(vars(action), prog=prog)
    for name, value in list(params.items()):
        if hasattr(value, "__name__"):
            params[name] = value.__name__
    if params.get("choices") is not None:
        params["choices"] = ", ".join(str(c) for c in params["choices"])
    try:
        return action.help % params
    except (KeyError, TypeError, ValueError):
        return action.help


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


# --- writing an argv -------------------------------------------------------


def _text(field: dict, value: Any) -> str:
    if value is None or value is False:
        return ""
    if value is True or not isinstance(value, (str, int, float)):
        raise InvalidRequest(f"{field['label']}: expected a value, got {value!r}")
    return str(value).strip()


def _validate(argv: list[str]) -> None:
    """Parse `argv` with the real parser; raise `InvalidRequest` with its message.

    argparse reports by printing and calling `sys.exit`. Rather than redirect
    the process-global stderr (this runs on a server thread, beside others),
    each parser in a fresh tree gets an `error` that raises instead.
    """
    from sdm import cli

    def error(message: str):
        raise InvalidRequest(message)

    parser = cli.build_parser()
    parser.error = error  # type: ignore[method-assign]
    for sub in _subparsers(parser).choices.values():
        sub.error = error  # type: ignore[method-assign]
    parser.parse_args(argv)


def _join(parts: list[str]) -> str:
    """Quote like the platform's own command line, so the line can be pasted."""
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)
