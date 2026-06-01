from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .doctor import doctor_report_to_dict, run_doctor
from .elm327 import ElmError, connect_auto
from .obd import scan as scan_bike, scan_report_to_dict
from .report import analyze_files, format_analysis, format_analysis_html
from .uds import (
    ModuleTarget,
    discover_modules,
    discovered_modules_to_dict,
    load_module_profile,
    module_profile_to_dict,
    profile_from_discovery,
    module_results_to_dict,
    scan_modules,
)


@dataclass(frozen=True)
class BundleResult:
    directory: Path
    doctor_path: Path
    standard_path: Optional[Path]
    module_path: Optional[Path]
    summary_path: Path
    html_path: Optional[Path]
    complete: bool
    discovery_path: Optional[Path] = None
    discovered_profile_path: Optional[Path] = None


def collect_diagnostics(
    output_root: str,
    port: Optional[str],
    baudrate: Optional[int],
    protocol: str,
    timeout: float,
    module_profile_path: str,
    extra_headers: Optional[list[str]],
    status_mask_text: str,
    discover_headers: bool = False,
    discovery_start_header: str = "700",
    discovery_end_header: str = "7EF",
) -> BundleResult:
    directory = next_report_directory(Path(output_root))
    directory.mkdir(parents=True, exist_ok=False)

    status_mask = parse_status_mask(status_mask_text)
    doctor = run_doctor(port, baudrate, protocol, timeout=timeout)
    doctor_path = directory / "doctor.json"
    write_json(doctor_path, doctor_report_to_dict(doctor))

    standard_path: Optional[Path] = None
    module_path: Optional[Path] = None
    discovery_path: Optional[Path] = None
    discovered_profile_path: Optional[Path] = None
    summary_path = directory / "summary.txt"
    html_path: Optional[Path] = None

    if not doctor.ecu_ok:
        summary_path.write_text(format_doctor_only_summary(doctor_report_to_dict(doctor)), encoding="utf-8")
        html_path = directory / "report.html"
        html_path.write_text(format_doctor_only_html(doctor_report_to_dict(doctor)), encoding="utf-8")
        return BundleResult(directory, doctor_path, standard_path, module_path, summary_path, html_path, complete=False)

    with connect_auto(port, baudrate, protocol, timeout=timeout) as elm:
        standard = scan_bike(elm, include_snapshot=True, include_freeze_frame=True)
    standard_path = directory / "standard-scan.json"
    write_json(standard_path, scan_report_to_dict(standard))

    profile = load_module_profile(module_profile_path)
    module_protocol = profile.protocol if protocol == "auto" and profile.protocol else protocol
    targets = list(profile.modules)
    for header in extra_headers or []:
        targets.append(ModuleTarget(name=f"manual {header.upper()}", tx_header=header))

    with connect_auto(port, baudrate, module_protocol, timeout=timeout) as elm:
        modules = scan_modules(elm, targets, status_mask=status_mask)
    module_path = directory / "module-scan.json"
    write_json(
        module_path,
        {
            "profile": profile.name,
            "protocol": module_protocol,
            "status_mask": f"0x{status_mask:02X}",
            "modules": module_results_to_dict(modules),
        },
    )

    if discover_headers:
        with connect_auto(port, baudrate, module_protocol, timeout=timeout) as elm:
            discovered = discover_modules(
                elm,
                start_header=discovery_start_header,
                end_header=discovery_end_header,
                status_mask=status_mask,
            )
        discovery_data = {
            "start_header": discovery_start_header.upper(),
            "end_header": discovery_end_header.upper(),
            "status_mask": f"0x{status_mask:02X}",
            "modules": discovered_modules_to_dict(discovered),
        }
        discovery_path, discovered_profile_path = write_discovery_artifacts(
            directory,
            discovery_data,
            protocol=module_protocol,
        )

    analysis = analyze_files(str(standard_path), str(module_path))
    summary_path.write_text(format_analysis(analysis), encoding="utf-8")
    html_path = directory / "report.html"
    html_path.write_text(format_analysis_html(analysis), encoding="utf-8")
    return BundleResult(
        directory,
        doctor_path,
        standard_path,
        module_path,
        summary_path,
        html_path,
        complete=True,
        discovery_path=discovery_path,
        discovered_profile_path=discovered_profile_path,
    )


def next_report_directory(output_root: Path, now: Optional[datetime] = None) -> Path:
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    base = output_root / f"tigerdiag-{timestamp}"
    if not base.exists():
        return base
    for index in range(2, 100):
        candidate = output_root / f"tigerdiag-{timestamp}-{index}"
        if not candidate.exists():
            return candidate
    raise ElmError(f"Could not find an unused report directory under {output_root}")


def parse_status_mask(text: str) -> int:
    try:
        value = int(text, 16)
    except ValueError as exc:
        raise ElmError("--status-mask must be a hexadecimal byte, for example FF or 08") from exc
    if value < 0 or value > 0xFF:
        raise ElmError("--status-mask must be between 00 and FF")
    return value


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_discovery_artifacts(directory: Path, discovery_data: dict, protocol: str) -> tuple[Path, Optional[Path]]:
    discovery_path = directory / "discovered-modules.json"
    write_json(discovery_path, discovery_data)

    try:
        profile = profile_from_discovery(
            discovery_data,
            name="Triumph Tiger discovered module profile",
            protocol=protocol,
        )
    except ElmError:
        return discovery_path, None

    profile_path = directory / "discovered-module-profile.json"
    write_json(profile_path, module_profile_to_dict(profile))
    return discovery_path, profile_path


def format_doctor_only_summary(doctor: dict) -> str:
    lines = [
        "TigerDiag collection did not reach the ECU.",
        "",
        "Saved doctor.json with serial-port and adapter troubleshooting details.",
        "",
        f"adapter_ok: {doctor.get('adapter_ok')}",
        f"ecu_ok: {doctor.get('ecu_ok')}",
    ]
    if doctor.get("ecu_error"):
        lines.append(f"ecu_error: {doctor['ecu_error']}")
    notes = doctor.get("notes") or []
    if notes:
        lines.append("")
        lines.append("Notes:")
        for note in notes:
            lines.append(f"- {note}")
    return "\n".join(lines) + "\n"


def format_doctor_only_html(doctor: dict) -> str:
    notes = doctor.get("notes") or []
    note_items = "\n".join(f"<li>{escape_html(str(note))}</li>" for note in notes)
    ecu_error = doctor.get("ecu_error")
    ecu_error_html = f"<p><strong>ECU error:</strong> {escape_html(str(ecu_error))}</p>" if ecu_error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TigerDiag Connection Report</title>
  <style>
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f9;
      color: #17202a;
      line-height: 1.5;
    }}
    main {{
      width: min(900px, calc(100% - 32px));
      margin: 32px auto;
      background: white;
      border: 1px solid #d7dde5;
      border-radius: 8px;
      padding: 24px;
    }}
    h1 {{ margin-top: 0; }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      background: #eef2f7;
      padding: 2px 5px;
      border-radius: 4px;
    }}
  </style>
</head>
<body>
<main>
  <h1>TigerDiag Connection Report</h1>
  <p>TigerDiag could not reach the ECU, so only connection troubleshooting files were saved.</p>
  <p><strong>Adapter OK:</strong> {escape_html(str(doctor.get("adapter_ok")))}</p>
  <p><strong>ECU OK:</strong> {escape_html(str(doctor.get("ecu_ok")))}</p>
  {ecu_error_html}
  <h2>Next Checks</h2>
  <ul>{note_items}</ul>
  <p>After fixing connection setup, run <code>tigerdiag collect --port /dev/cu.usbserial-XXXX --protocol can_11_500</code> again.</p>
</main>
</body>
</html>
"""


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
