from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .elm327 import Elm327, ElmError


@dataclass
class ServiceCommand:
    command: str
    expect: Optional[str] = None
    delay_seconds: float = 0.05
    note: str = ""


@dataclass
class ServiceProfile:
    name: str
    description: str
    protocol: str
    commands: List[ServiceCommand]
    variables: Dict[str, str]


def load_profile(path: str) -> ServiceProfile:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    commands = [
        ServiceCommand(
            command=item["command"],
            expect=item.get("expect"),
            delay_seconds=float(item.get("delay_seconds", 0.05)),
            note=item.get("note", ""),
        )
        for item in data.get("commands", [])
    ]
    return ServiceProfile(
        name=data.get("name", Path(path).stem),
        description=data.get("description", ""),
        protocol=data.get("protocol", "auto"),
        commands=commands,
        variables={str(key): str(value) for key, value in data.get("variables", {}).items()},
    )


def render_profile(profile: ServiceProfile, variables: Optional[Dict[str, str]] = None) -> ServiceProfile:
    merged = dict(profile.variables)
    merged.update(variables or {})
    required = sorted(required_variables(profile))
    missing = [name for name in required if name not in merged]
    if missing:
        raise ElmError(f"Missing service profile variable(s): {', '.join(missing)}")

    rendered_commands = [
        ServiceCommand(
            command=render_template(item.command, merged),
            expect=render_template(item.expect, merged) if item.expect else None,
            delay_seconds=item.delay_seconds,
            note=render_template(item.note, merged) if item.note else "",
        )
        for item in profile.commands
    ]
    return ServiceProfile(
        name=profile.name,
        description=render_template(profile.description, merged) if profile.description else "",
        protocol=profile.protocol,
        commands=rendered_commands,
        variables=merged,
    )


def render_template(text: str, variables: Dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in variables:
            raise ElmError(f"Missing service profile variable: {name}")
        return variables[name]

    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, text)


def required_variables(profile: ServiceProfile) -> set[str]:
    names: set[str] = set()
    for text in [profile.description] + [
        value
        for command in profile.commands
        for value in (command.command, command.expect or "", command.note)
    ]:
        names.update(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", text or ""))
    return names


def parse_variable_assignments(assignments: Optional[List[str]]) -> Dict[str, str]:
    output: Dict[str, str] = {}
    for item in assignments or []:
        if "=" not in item:
            raise ElmError(f"Variable assignment must be KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            raise ElmError(f"Invalid variable name {key!r}")
        output[key] = value.strip()
    return output


def dry_run_profile(profile: ServiceProfile, variables: Optional[Dict[str, str]] = None) -> List[str]:
    rendered = render_profile(profile, variables)
    lines = [
        f"profile: {rendered.name}",
        f"protocol: {rendered.protocol}",
    ]
    if rendered.description:
        lines.append(f"description: {rendered.description}")
    if rendered.variables:
        lines.append("variables:")
        for key in sorted(rendered.variables):
            lines.append(f"  {key}={rendered.variables[key]}")
    lines.append("commands:")
    if not rendered.commands:
        lines.append("  none")
    for index, item in enumerate(rendered.commands, start=1):
        lines.append(f"  {index}. {item.command}")
        if item.expect:
            lines.append(f"     expect: {item.expect}")
        if item.note:
            lines.append(f"     note: {item.note}")
    return lines


def run_profile(elm: Elm327, profile: ServiceProfile, variables: Optional[Dict[str, str]] = None) -> List[str]:
    rendered = render_profile(profile, variables)
    if not rendered.commands:
        raise ElmError(
            "Service profile has no commands. TigerDiag will not guess proprietary service reset bytes."
        )

    transcript: List[str] = []
    for item in rendered.commands:
        lines = elm.command(item.command)
        joined = " ".join(lines)
        transcript.append(f"> {item.command}\n{joined}")
        if item.expect and item.expect.upper() not in joined.upper():
            raise ElmError(f"Unexpected response to {item.command}. Expected text containing {item.expect!r}.")
        if item.delay_seconds:
            time.sleep(item.delay_seconds)
    return transcript
