from __future__ import annotations

import json
from html import escape
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .dtc import severity_for_code, suggestion_for_code
from .elm327 import ElmError


SEVERITY_ORDER = {
    "high": 0,
    "medium": 1,
    "low": 2,
    "unknown": 3,
}


@dataclass(frozen=True)
class Finding:
    source: str
    code: str
    description: str
    suggestion: str
    severity: str
    status: str = ""
    raw: str = ""


@dataclass(frozen=True)
class AnalysisReport:
    standard_path: Optional[str]
    module_path: Optional[str]
    vin: Optional[str]
    mil_on: Optional[bool]
    reported_dtc_count: Optional[int]
    findings: List[Finding]
    module_responses: Dict[str, str]

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)


@dataclass(frozen=True)
class ComparisonReport:
    before: AnalysisReport
    after: AnalysisReport
    resolved: List[Finding]
    persistent: List[Finding]
    new: List[Finding]


def analyze_files(standard_path: Optional[str], module_path: Optional[str]) -> AnalysisReport:
    if not standard_path and not module_path:
        raise ElmError("Provide --standard, --modules, or both.")

    standard = load_json_file(standard_path) if standard_path else None
    modules = load_json_file(module_path) if module_path else None

    findings: List[Finding] = []
    if standard:
        findings.extend(findings_from_standard_scan(standard))
    if modules:
        findings.extend(findings_from_module_scan(modules))

    findings.sort(key=lambda item: (SEVERITY_ORDER.get(item.severity, 99), item.source, item.code))

    return AnalysisReport(
        standard_path=standard_path,
        module_path=module_path,
        vin=standard.get("vin") if standard else None,
        mil_on=standard.get("mil", {}).get("on") if standard and standard.get("mil") else None,
        reported_dtc_count=standard.get("mil", {}).get("reported_dtc_count")
        if standard and standard.get("mil")
        else None,
        findings=findings,
        module_responses=module_response_summary(modules) if modules else {},
    )


def compare_reports(
    before_standard: Optional[str],
    before_modules: Optional[str],
    after_standard: Optional[str],
    after_modules: Optional[str],
) -> ComparisonReport:
    if not before_standard and not before_modules:
        raise ElmError("Provide --before-standard, --before-modules, or both.")
    if not after_standard and not after_modules:
        raise ElmError("Provide --after-standard, --after-modules, or both.")

    before = analyze_files(before_standard, before_modules)
    after = analyze_files(after_standard, after_modules)

    before_by_key = {finding_key(item): item for item in before.findings}
    after_by_key = {finding_key(item): item for item in after.findings}

    resolved = [before_by_key[key] for key in sorted(before_by_key.keys() - after_by_key.keys())]
    persistent = [after_by_key[key] for key in sorted(before_by_key.keys() & after_by_key.keys())]
    new = [after_by_key[key] for key in sorted(after_by_key.keys() - before_by_key.keys())]
    return ComparisonReport(before=before, after=after, resolved=resolved, persistent=persistent, new=new)


def finding_key(finding: Finding) -> tuple[str, str, str, str]:
    return (finding.source, finding.code, finding.status, finding.raw)


def load_json_file(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ElmError(f"Report file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ElmError(f"Report file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ElmError(f"Report file must contain a JSON object: {path}")
    return data


def findings_from_standard_scan(report: dict) -> List[Finding]:
    output: List[Finding] = []
    standard_codes: set[str] = set()
    dtc_groups = report.get("dtcs", {})
    if isinstance(dtc_groups, dict):
        for group, items in dtc_groups.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or not item.get("code"):
                    continue
                code = str(item["code"])
                standard_codes.add(code)
                output.append(
                    Finding(
                        source=f"standard OBD {group}",
                        code=code,
                        description=str(item.get("description") or ""),
                        suggestion=str(item.get("suggestion") or suggestion_for_code(code)),
                        severity=severity_for_standard_group(code, str(group)),
                        status=str(group),
                    )
                )

    output.extend(findings_from_snapshot(report.get("snapshot", [])))
    output.extend(findings_from_freeze_frame(report.get("freeze_frame"), standard_codes=standard_codes))
    return output


def findings_from_snapshot(snapshot: object) -> List[Finding]:
    if not isinstance(snapshot, list):
        return []

    output: List[Finding] = []
    for item in snapshot:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue

        if name == "control module voltage" and value < 12.0:
            severity = "high" if value < 11.5 else "medium"
            output.append(
                Finding(
                    source="sensor snapshot",
                    code="VOLTAGE_LOW",
                    description=f"Control module voltage is {value:g} V.",
                    suggestion="Charge/test the battery and verify charging voltage before diagnosing intermittent sensor or CAN faults.",
                    severity=severity,
                )
            )
        if "fuel trim" in name and abs(value) >= 15.0:
            direction = "adding fuel" if value > 0 else "removing fuel"
            output.append(
                Finding(
                    source="sensor snapshot",
                    code="FUEL_TRIM_HIGH",
                    description=f"{name} is {value:g}%, so the ECU is {direction}.",
                    suggestion="Check intake leaks, exhaust leaks near oxygen sensors, fuel pressure, injector condition, and sensor wiring.",
                    severity="medium",
                )
            )
    return output


def findings_from_freeze_frame(freeze_frame: object, standard_codes: Optional[set[str]] = None) -> List[Finding]:
    if not isinstance(freeze_frame, dict):
        return []
    code = freeze_frame.get("dtc")
    if not code or str(code) in (standard_codes or set()):
        return []

    return [
        Finding(
            source=f"freeze frame {freeze_frame.get('frame', 0)}",
            code=str(code),
            description="DTC associated with the stored freeze-frame snapshot.",
            suggestion=suggestion_for_code(str(code)),
            severity=severity_for_code(str(code)),
        )
    ]


def findings_from_module_scan(report: dict) -> List[Finding]:
    output: List[Finding] = []
    modules = report.get("modules", [])
    if not isinstance(modules, list):
        return output

    for module in modules:
        if not isinstance(module, dict):
            continue
        module_info = module.get("module", {})
        module_name = module_info.get("name", "unknown module") if isinstance(module_info, dict) else "unknown module"
        for item in module.get("dtcs", []) if isinstance(module.get("dtcs"), list) else []:
            if not isinstance(item, dict) or not item.get("code"):
                continue
            code = str(item["code"])
            flags = item.get("status_flags", [])
            flags_text = ", ".join(str(flag) for flag in flags) if isinstance(flags, list) else str(flags)
            output.append(
                Finding(
                    source=str(module_name),
                    code=code,
                    description=str(item.get("description") or ""),
                    suggestion=str(item.get("suggestion") or suggestion_for_code(code)),
                    severity=severity_for_module_code(code, flags if isinstance(flags, list) else []),
                    status=flags_text,
                    raw=str(item.get("raw") or ""),
                )
            )
    return output


def severity_for_standard_group(code: str, group: str) -> str:
    severity = severity_for_code(code)
    if group == "permanent" and severity == "medium":
        return "high"
    return severity


def severity_for_module_code(code: str, flags: Iterable[str]) -> str:
    flag_set = {str(flag) for flag in flags}
    if "warning_indicator_requested" in flag_set:
        return "high"
    if "confirmed" in flag_set and severity_for_code(code) == "medium":
        return "high"
    return severity_for_code(code)


def module_response_summary(report: Optional[dict]) -> Dict[str, str]:
    summary: Dict[str, str] = {}
    if not report:
        return summary
    modules = report.get("modules", [])
    if not isinstance(modules, list):
        return summary
    for module in modules:
        if not isinstance(module, dict):
            continue
        module_info = module.get("module", {})
        name = module_info.get("name", "unknown module") if isinstance(module_info, dict) else "unknown module"
        if not module.get("responded"):
            summary[str(name)] = f"no response ({module.get('error') or 'no data'})"
        elif module.get("dtcs"):
            summary[str(name)] = f"responded with {len(module.get('dtcs', []))} DTC(s)"
        else:
            summary[str(name)] = "responded, no DTCs decoded"
    return summary


def format_analysis(report: AnalysisReport) -> str:
    lines: List[str] = []
    lines.append("TigerDiag analysis")
    lines.append("==================")

    if report.vin:
        lines.append(f"VIN: {report.vin}")
    if report.mil_on is not None:
        mil = "ON" if report.mil_on else "off"
        count = report.reported_dtc_count if report.reported_dtc_count is not None else "unknown"
        lines.append(f"MIL: {mil} (reported DTC count: {count})")
    lines.append("")

    if not report.findings:
        lines.append("No DTCs were found in the supplied reports.")
        lines.append("Next: if the bike still shows a dash warning, run module-scan and include the JSON so non-engine modules can be checked.")
    else:
        lines.append("Findings:")
        for finding in report.findings:
            status = f" [{finding.status}]" if finding.status else ""
            raw = f" raw={finding.raw}" if finding.raw else ""
            lines.append(f"- {finding.severity.upper()}: {finding.code}{status}{raw} from {finding.source}")
            if finding.description:
                lines.append(f"  {finding.description}")
            lines.append(f"  Next: {finding.suggestion}")

    if report.module_responses:
        lines.append("")
        lines.append("Module responses:")
        for module, status in report.module_responses.items():
            lines.append(f"- {module}: {status}")

    lines.append("")
    lines.append("Before clearing codes: save these reports, fix obvious battery/connector issues first, then re-scan.")
    return "\n".join(lines)


def format_comparison(report: ComparisonReport) -> str:
    lines: List[str] = []
    lines.append("TigerDiag comparison")
    lines.append("====================")
    lines.append("")
    lines.append(f"Resolved: {len(report.resolved)}")
    lines.append(f"Persistent: {len(report.persistent)}")
    lines.append(f"New: {len(report.new)}")
    lines.append("")
    append_comparison_group(lines, "Resolved", report.resolved)
    append_comparison_group(lines, "Persistent", report.persistent)
    append_comparison_group(lines, "New", report.new)
    if not report.resolved and not report.persistent and not report.new:
        lines.append("No findings in either report.")
    lines.append("")
    lines.append("Next: persistent or new findings should be diagnosed before clearing codes again.")
    return "\n".join(lines)


def append_comparison_group(lines: List[str], title: str, findings: List[Finding]) -> None:
    if not findings:
        return
    lines.append(f"{title}:")
    for finding in findings:
        status = f" [{finding.status}]" if finding.status else ""
        raw = f" raw={finding.raw}" if finding.raw else ""
        lines.append(f"- {finding.severity.upper()}: {finding.code}{status}{raw} from {finding.source}")
        if finding.description:
            lines.append(f"  {finding.description}")
        lines.append(f"  Next: {finding.suggestion}")
    lines.append("")


def format_analysis_html(report: AnalysisReport, title: str = "TigerDiag Report") -> str:
    finding_cards = "\n".join(format_finding_html(finding) for finding in report.findings)
    if not finding_cards:
        finding_cards = (
            '<section class="empty">'
            "<h2>No DTCs Found</h2>"
            "<p>No DTCs were found in the supplied reports. If the dash still shows a warning, "
            "capture module-scan output so non-engine modules can be checked.</p>"
            "</section>"
        )

    module_rows = "\n".join(
        f"<tr><td>{escape(module)}</td><td>{escape(status)}</td></tr>"
        for module, status in report.module_responses.items()
    )
    module_section = ""
    if module_rows:
        module_section = (
            "<section>"
            "<h2>Module Responses</h2>"
            "<table><thead><tr><th>Module</th><th>Status</th></tr></thead>"
            f"<tbody>{module_rows}</tbody></table>"
            "</section>"
        )

    vin = escape(report.vin or "not reported")
    mil = "not reported"
    if report.mil_on is not None:
        mil_state = "ON" if report.mil_on else "off"
        mil = f"{mil_state} ({report.reported_dtc_count if report.reported_dtc_count is not None else 'unknown'} reported DTCs)"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #5b6673;
      --line: #d7dde5;
      --high: #b42318;
      --medium: #b54708;
      --low: #2f6b3f;
      --unknown: #4b5563;
      --accent: #175cd3;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    main {{
      width: min(1040px, calc(100% - 32px));
      margin: 32px auto;
    }}
    header, section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 16px;
    }}
    h1, h2, h3, p {{ margin-top: 0; }}
    h1 {{ font-size: 28px; margin-bottom: 8px; }}
    h2 {{ font-size: 18px; margin-bottom: 12px; }}
    h3 {{ font-size: 16px; margin-bottom: 6px; }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .meta div {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      background: #fbfcfe;
    }}
    .label {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .finding {{
      border-left: 5px solid var(--unknown);
    }}
    .finding.high {{ border-left-color: var(--high); }}
    .finding.medium {{ border-left-color: var(--medium); }}
    .finding.low {{ border-left-color: var(--low); }}
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      color: white;
      font-size: 12px;
      font-weight: 700;
      background: var(--unknown);
      margin-right: 8px;
    }}
    .badge.high {{ background: var(--high); }}
    .badge.medium {{ background: var(--medium); }}
    .badge.low {{ background: var(--low); }}
    .code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-weight: 700;
    }}
    .next {{
      border-top: 1px solid var(--line);
      padding-top: 10px;
      margin-top: 10px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
    footer {{ color: var(--muted); font-size: 13px; margin-top: 20px; }}
  </style>
</head>
<body>
<main>
  <header>
    <h1>{escape(title)}</h1>
    <p>Diagnostic summary generated from TigerDiag JSON captures.</p>
    <div class="meta">
      <div><span class="label">VIN</span>{vin}</div>
      <div><span class="label">MIL</span>{escape(mil)}</div>
      <div><span class="label">Findings</span>{len(report.findings)}</div>
    </div>
  </header>
  <section>
    <h2>Findings</h2>
    {finding_cards}
  </section>
  {module_section}
  <footer>Before clearing codes: save these reports, fix obvious battery or connector issues first, then re-scan.</footer>
</main>
</body>
</html>
"""


def format_finding_html(finding: Finding) -> str:
    severity = finding.severity if finding.severity in SEVERITY_ORDER else "unknown"
    status = f" [{escape(finding.status)}]" if finding.status else ""
    raw = f" raw={escape(finding.raw)}" if finding.raw else ""
    description = f"<p>{escape(finding.description)}</p>" if finding.description else ""
    return (
        f'<article class="finding {escape(severity)}">'
        f'<h3><span class="badge {escape(severity)}">{escape(severity.upper())}</span>'
        f'<span class="code">{escape(finding.code)}</span>{status}{raw}</h3>'
        f'<p><strong>Source:</strong> {escape(finding.source)}</p>'
        f"{description}"
        f'<p class="next"><strong>Next:</strong> {escape(finding.suggestion)}</p>'
        "</article>"
    )
