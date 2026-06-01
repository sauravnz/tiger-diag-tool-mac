from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Optional

from . import __version__
from .bundle import collect_diagnostics, parse_status_mask
from .dtc import Dtc
from .doctor import doctor_report_to_dict, run_doctor
from .elm327 import COMMON_BAUDRATES, PROTOCOLS, Elm327, ElmError, connect_auto, list_serial_candidates
from .obd import clear_dtcs, scan as scan_bike, scan_report_to_dict
from .pids import freeze_frame_to_dict, read_freeze_frame, read_snapshot, snapshot_to_dict
from .report import compare_reports, analyze_files, format_analysis, format_comparison
from .service import dry_run_profile, load_profile, parse_variable_assignments, run_profile
from .uds import (
    ModuleTarget,
    discover_modules,
    discovered_modules_to_dict,
    load_discovery_profile,
    load_module_profile,
    module_profile_to_dict,
    module_results_to_dict,
    scan_modules,
)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        return args.func(args)
    except ElmError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tigerdiag",
        description="Mac-friendly ELM327 diagnostics for Triumph Tiger motorcycles.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(required=True)

    ports = sub.add_parser("list-ports", help="List likely macOS serial ports for the OBD adapter.")
    ports.set_defaults(func=cmd_list_ports)

    doctor = sub.add_parser("doctor", help="Check macOS serial setup, ELM adapter response, and ECU reachability.")
    add_connection_args(doctor)
    doctor.add_argument("--json", action="store_true", help="Print troubleshooting results as JSON.")
    doctor.set_defaults(func=cmd_doctor)

    info = sub.add_parser("adapter-info", help="Connect and print ELM adapter details.")
    add_connection_args(info)
    info.set_defaults(func=cmd_adapter_info)

    scan = sub.add_parser("scan", help="Read VIN, MIL state, and stored/pending/permanent DTCs.")
    add_connection_args(scan)
    scan.add_argument("--snapshot", action="store_true", help="Also read common live sensor PIDs.")
    scan.add_argument("--freeze-frame", action="store_true", help="Also read standard OBD freeze-frame data.")
    scan.add_argument("--json", action="store_true", help="Print the report as JSON.")
    scan.set_defaults(func=cmd_scan)

    snapshot = sub.add_parser("snapshot", help="Read common standard OBD live sensor values.")
    add_connection_args(snapshot)
    snapshot.add_argument("--pid", action="append", help="Specific one-byte PID to read. Can be repeated.")
    snapshot.add_argument("--json", action="store_true", help="Print sensor readings as JSON.")
    snapshot.set_defaults(func=cmd_snapshot)

    freeze = sub.add_parser("freeze-frame", help="Read standard OBD mode 02 freeze-frame data.")
    add_connection_args(freeze)
    freeze.add_argument("--frame", type=int, default=0, help="Freeze-frame number. Most bikes expose frame 0.")
    freeze.add_argument("--pid", action="append", help="Specific one-byte PID to read from the freeze frame. Can be repeated.")
    freeze.add_argument("--json", action="store_true", help="Print freeze-frame data as JSON.")
    freeze.set_defaults(func=cmd_freeze_frame)

    modules = sub.add_parser("module-scan", help="Read UDS DTCs from configured CAN module headers.")
    add_connection_args(modules)
    modules.add_argument(
        "--profile",
        default="profiles/tiger-900-readonly-modules.json",
        help="JSON module profile to use.",
    )
    modules.add_argument(
        "--header",
        action="append",
        help="Extra CAN request header to scan. Can be repeated, e.g. --header 7E0 --header 760.",
    )
    modules.add_argument(
        "--status-mask",
        default="FF",
        help="UDS DTC status mask for service 19 02. Default FF asks for all reported DTC states.",
    )
    modules.add_argument("--json", action="store_true", help="Print module results as JSON.")
    modules.set_defaults(func=cmd_module_scan)

    discover = sub.add_parser("discover-modules", help="Read-only discovery of responding 11-bit CAN diagnostic headers.")
    add_connection_args(discover)
    discover.add_argument("--start-header", default="700", help="First 11-bit CAN request header to try.")
    discover.add_argument("--end-header", default="7EF", help="Last 11-bit CAN request header to try.")
    discover.add_argument(
        "--status-mask",
        default="FF",
        help="UDS DTC status mask for service 19 02. Default FF asks for all reported DTC states.",
    )
    discover.add_argument("--json", action="store_true", help="Print discovery results as JSON.")
    discover.set_defaults(func=cmd_discover_modules)

    profile_from_discovery = sub.add_parser(
        "profile-from-discovery",
        help="Create a module-scan profile from discover-modules JSON output.",
    )
    profile_from_discovery.add_argument("--discovery", required=True, help="Path to discovered-modules.json.")
    profile_from_discovery.add_argument("--output", required=True, help="Path for the generated module profile JSON.")
    profile_from_discovery.add_argument("--name", default="Triumph Tiger discovered module profile", help="Generated profile name.")
    profile_from_discovery.add_argument("--protocol", default="can_11_500", choices=sorted(PROTOCOLS), help="Protocol for the generated profile.")
    profile_from_discovery.set_defaults(func=cmd_profile_from_discovery)

    analyze = sub.add_parser("analyze", help="Analyze saved scan JSON and print next diagnostic steps.")
    analyze.add_argument("--standard", help="JSON file from: tigerdiag scan --json")
    analyze.add_argument("--modules", help="JSON file from: tigerdiag module-scan --json")
    analyze.set_defaults(func=cmd_analyze)

    compare = sub.add_parser("compare", help="Compare before/after diagnostic JSON reports.")
    compare.add_argument("--before-standard", help="Earlier standard-scan.json.")
    compare.add_argument("--before-modules", help="Earlier module-scan.json.")
    compare.add_argument("--after-standard", help="Later standard-scan.json.")
    compare.add_argument("--after-modules", help="Later module-scan.json.")
    compare.set_defaults(func=cmd_compare)

    collect = sub.add_parser("collect", help="Run doctor, standard scan, module scan, and save a report bundle.")
    add_connection_args(collect)
    collect.add_argument("--output-dir", default="reports", help="Directory where a timestamped report folder is created.")
    collect.add_argument(
        "--profile",
        default="profiles/tiger-900-readonly-modules.json",
        help="JSON module profile to use for the module scan.",
    )
    collect.add_argument(
        "--header",
        action="append",
        help="Extra CAN request header for the module scan. Can be repeated.",
    )
    collect.add_argument(
        "--status-mask",
        default="FF",
        help="UDS DTC status mask for service 19 02. Default FF asks for all reported DTC states.",
    )
    collect.add_argument(
        "--discover-modules",
        action="store_true",
        help="Also run read-only diagnostic header discovery and save discovery artifacts.",
    )
    collect.add_argument("--discovery-start-header", default="700", help="First 11-bit CAN request header for collect discovery.")
    collect.add_argument("--discovery-end-header", default="7EF", help="Last 11-bit CAN request header for collect discovery.")
    collect.set_defaults(func=cmd_collect)

    clear = sub.add_parser("clear-dtcs", help="Clear engine/emissions DTCs and MIL using standard OBD mode 04.")
    add_connection_args(clear)
    clear.add_argument("--yes", action="store_true", help="Confirm that DTC clearing should be performed.")
    clear.set_defaults(func=cmd_clear_dtcs)

    raw = sub.add_parser("raw", help="Send a raw ELM/OBD command and print the response.")
    add_connection_args(raw)
    raw.add_argument("--header", help="Optional diagnostic request header to set first, e.g. 7E0.")
    raw.add_argument("--show-headers", action="store_true", help="Ask the ELM adapter to include response headers.")
    raw.add_argument("command", help="Command to send, for example ATDP, 0100, 03, or 0902.")
    raw.set_defaults(func=cmd_raw)

    service = sub.add_parser(
        "service-reset",
        help="Run a guarded proprietary service reset profile. Requires verified local command bytes.",
    )
    add_connection_args(service)
    service.add_argument("--profile", required=True, help="Path to a JSON service command profile.")
    service.add_argument("--set", action="append", dest="variables", help="Set a service profile variable as KEY=VALUE.")
    service.add_argument("--dry-run", action="store_true", help="Render the profile and commands without connecting or sending.")
    service.add_argument(
        "--i-understand-risk",
        action="store_true",
        help="Required before any proprietary write profile is sent.",
    )
    service.set_defaults(func=cmd_service_reset)

    return parser


def add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--port", help="Serial port, e.g. /dev/cu.usbserial-XXXX. Omit for auto-detect.")
    parser.add_argument(
        "--baud",
        type=int,
        choices=COMMON_BAUDRATES,
        help="Adapter baud rate. Omit to try common ELM327 rates.",
    )
    parser.add_argument(
        "--protocol",
        default="auto",
        choices=sorted(PROTOCOLS),
        help="ELM protocol. Later Tigers usually use ISO15765-4 CAN, so can_11_500 is a useful fallback.",
    )
    parser.add_argument("--timeout", type=float, default=2.0, help="Serial read timeout in seconds.")


def cmd_list_ports(args: argparse.Namespace) -> int:
    ports = list_serial_candidates()
    if not ports:
        print("No serial ports found.")
        return 1

    for port in ports:
        detail = " ".join(part for part in (port.description, port.hwid) if part)
        print(f"{port.device}" + (f"  {detail}" if detail else ""))
    return 0


def cmd_adapter_info(args: argparse.Namespace) -> int:
    with connect_auto(args.port, args.baud, args.protocol, timeout=args.timeout, require_ecu=False) as elm:
        from .obd import adapter_info

        print_connection(elm)
        for key, value in adapter_info(elm).items():
            print(f"{key}: {value}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    report = run_doctor(args.port, args.baud, args.protocol, timeout=args.timeout)
    if args.json:
        print(json.dumps(doctor_report_to_dict(report), indent=2))
        return 0 if report.ecu_ok else 1

    print("TigerDiag doctor")
    print("================")
    print()
    print("Serial ports:")
    if not report.ports:
        print("  none found")
    for item in report.ports:
        marker = "likely" if item["likely"] else "unlikely"
        detail = " ".join(part for part in (item["description"], item["hwid"]) if part)
        print(f"  {item['device']}  {marker} score={item['score']}" + (f"  {detail}" if detail else ""))

    print()
    if report.selected_port:
        print(f"ELM adapter: OK on {report.selected_port} @ {report.selected_baud}")
        for key, value in report.adapter.items():
            print(f"  {key}: {value}")
    else:
        print("ELM adapter: not connected")

    print(f"ECU probe: {'OK' if report.ecu_ok else 'not ready'}")
    if report.ecu_error:
        print(f"  error: {report.ecu_error}")
    if report.notes:
        print()
        print("Notes:")
        for note in report.notes:
            print(f"  - {note}")
    return 0 if report.ecu_ok else 1


def cmd_scan(args: argparse.Namespace) -> int:
    with connect_auto(args.port, args.baud, args.protocol, timeout=args.timeout) as elm:
        report = scan_bike(elm, include_snapshot=args.snapshot, include_freeze_frame=args.freeze_frame)
        if args.json:
            print(json.dumps(scan_report_to_dict(report), indent=2))
            return 0

        print_connection(elm)
        print()
        for key, value in report.adapter.items():
            print(f"{key}: {value}")
        print(f"vin: {report.vin or 'not reported'}")

        if report.mil:
            print(f"mil: {'ON' if report.mil.mil_on else 'off'}")
            print(f"reported_dtc_count: {report.mil.dtc_count}")
        else:
            print("mil: not reported")

        print()
        print_dtc_group("stored", report.dtcs["stored"])
        print_dtc_group("pending", report.dtcs["pending"])
        print_dtc_group("permanent", report.dtcs["permanent"])

        if not report.has_dtcs:
            print("No DTCs reported by standard OBD-II modes.")
        if report.snapshot:
            print()
            print_snapshot(report.snapshot)
        if report.freeze_frame:
            print()
            print_freeze_frame(report.freeze_frame)
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    with connect_auto(args.port, args.baud, args.protocol, timeout=args.timeout) as elm:
        readings = read_snapshot(elm, pids=args.pid)
        if args.json:
            print(json.dumps({"snapshot": snapshot_to_dict(readings)}, indent=2))
            return 0
        print_connection(elm)
        print_snapshot(readings)
    return 0


def cmd_freeze_frame(args: argparse.Namespace) -> int:
    with connect_auto(args.port, args.baud, args.protocol, timeout=args.timeout) as elm:
        report = read_freeze_frame(elm, frame=args.frame, pids=args.pid)
        if args.json:
            print(json.dumps({"freeze_frame": freeze_frame_to_dict(report)}, indent=2))
            return 0
        print_connection(elm)
        print_freeze_frame(report)
    return 0


def cmd_module_scan(args: argparse.Namespace) -> int:
    profile = load_module_profile(args.profile)
    protocol = args.protocol
    if args.protocol == "auto" and profile.protocol:
        protocol = profile.protocol

    targets = list(profile.modules)
    for header in args.header or []:
        targets.append(ModuleTarget(name=f"manual {header.upper()}", tx_header=header))

    status_mask = parse_status_mask(args.status_mask)

    with connect_auto(args.port, args.baud, protocol, timeout=args.timeout) as elm:
        results = scan_modules(elm, targets, status_mask=status_mask)
        if args.json:
            print(
                json.dumps(
                    {
                        "profile": profile.name,
                        "protocol": protocol,
                        "status_mask": f"0x{status_mask:02X}",
                        "modules": module_results_to_dict(results),
                    },
                    indent=2,
                )
            )
            return 0

        print_connection(elm)
        print(f"profile: {profile.name}")
        if profile.description:
            print(f"description: {profile.description}")
        print(f"status_mask: 0x{status_mask:02X}")
        print()
        for result in results:
            print(f"{result.target.name} ({result.target.tx_header})")
            if not result.responded:
                print(f"  no response: {result.error or 'no data'}")
                continue
            if result.raw_lines:
                print(f"  raw: {' | '.join(result.raw_lines)}")
            if not result.dtcs:
                print("  no UDS DTCs reported")
                continue
            for item in result.dtcs:
                flags = ", ".join(item.status_flags) if item.status_flags else "none"
                print(f"  {item.code}  raw={item.raw} status=0x{item.status:02X} ({flags})")
                print(f"    {item.description}")
                print(f"    next: {item.suggestion}")
    return 0


def cmd_discover_modules(args: argparse.Namespace) -> int:
    status_mask = parse_status_mask(args.status_mask)
    with connect_auto(args.port, args.baud, args.protocol, timeout=args.timeout) as elm:
        results = discover_modules(
            elm,
            start_header=args.start_header,
            end_header=args.end_header,
            status_mask=status_mask,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "start_header": args.start_header.upper(),
                        "end_header": args.end_header.upper(),
                        "status_mask": f"0x{status_mask:02X}",
                        "modules": discovered_modules_to_dict(results),
                    },
                    indent=2,
                )
            )
            return 0

        print_connection(elm)
        print(f"discovery_range: {args.start_header.upper()}..{args.end_header.upper()}")
        print(f"status_mask: 0x{status_mask:02X}")
        if not results:
            print("no responding module headers found")
            return 0
        for item in results:
            print(f"{item.tx_header}: {item.response_kind}, dtcs={item.dtc_count}")
            print(f"  raw: {' | '.join(item.raw_lines)}")
    return 0


def cmd_profile_from_discovery(args: argparse.Namespace) -> int:
    profile = load_discovery_profile(args.discovery, name=args.name, protocol=args.protocol)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(module_profile_to_dict(profile), indent=2) + "\n", encoding="utf-8")
    print(f"profile: {output}")
    print(f"modules: {len(profile.modules)}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    report = analyze_files(args.standard, args.modules)
    print(format_analysis(report))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    report = compare_reports(
        before_standard=args.before_standard,
        before_modules=args.before_modules,
        after_standard=args.after_standard,
        after_modules=args.after_modules,
    )
    print(format_comparison(report))
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    result = collect_diagnostics(
        output_root=args.output_dir,
        port=args.port,
        baudrate=args.baud,
        protocol=args.protocol,
        timeout=args.timeout,
        module_profile_path=args.profile,
        extra_headers=args.header,
        status_mask_text=args.status_mask,
        discover_headers=args.discover_modules,
        discovery_start_header=args.discovery_start_header,
        discovery_end_header=args.discovery_end_header,
    )
    print(f"report_dir: {result.directory}")
    print(f"doctor: {result.doctor_path}")
    if result.standard_path:
        print(f"standard_scan: {result.standard_path}")
    if result.module_path:
        print(f"module_scan: {result.module_path}")
    print(f"summary: {result.summary_path}")
    if result.html_path:
        print(f"html_report: {result.html_path}")
    if result.discovery_path:
        print(f"discovered_modules: {result.discovery_path}")
    if result.discovered_profile_path:
        print(f"discovered_profile: {result.discovered_profile_path}")
    return 0 if result.complete else 1


def cmd_clear_dtcs(args: argparse.Namespace) -> int:
    if not args.yes:
        raise ElmError("Refusing to clear DTCs without --yes. Run scan first and record the codes.")
    with connect_auto(args.port, args.baud, args.protocol, timeout=args.timeout) as elm:
        print_connection(elm)
        lines = clear_dtcs(elm)
        print("clear_dtc_response: " + (" ".join(lines) if lines else "OK"))
        print("Turn ignition off for about 60 seconds, then scan again.")
    return 0


def cmd_raw(args: argparse.Namespace) -> int:
    with connect_auto(args.port, args.baud, args.protocol, timeout=args.timeout) as elm:
        print_connection(elm)
        if args.header:
            elm.set_header(args.header)
        if args.show_headers:
            elm.show_headers(True)
        lines = elm.command(args.command)
        for line in lines:
            print(line)
    return 0


def cmd_service_reset(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    variables = parse_variable_assignments(args.variables)
    if args.dry_run:
        print("\n".join(dry_run_profile(profile, variables)))
        return 0

    if not args.i_understand_risk:
        raise ElmError("Refusing to run proprietary service profile without --i-understand-risk.")

    protocol = args.protocol
    if args.protocol == "auto" and profile.protocol:
        protocol = profile.protocol

    with connect_auto(args.port, args.baud, protocol, timeout=args.timeout) as elm:
        print_connection(elm)
        print(f"profile: {profile.name}")
        if profile.description:
            print(f"description: {profile.description}")
        transcript = run_profile(elm, profile, variables)
        print("\n".join(transcript))
    return 0


def print_connection(elm: Elm327) -> None:
    print(f"connected: {elm.port} @ {elm.baudrate}")


def print_dtc_group(name: str, codes: list[Dtc]) -> None:
    print(f"{name}_dtcs:")
    if not codes:
        print("  none")
        return
    for item in codes:
        print(f"  {item.code}  {item.description}")
        print(f"    next: {item.suggestion}")


def print_snapshot(readings) -> None:
    print("sensor_snapshot:")
    if not readings:
        print("  no supported common sensor PIDs reported")
        return
    for item in readings:
        print(f"  {item.name}: {item.value} {item.unit} (PID {item.pid})")


def print_freeze_frame(report) -> None:
    print(f"freeze_frame_{report.frame}:")
    print(f"  dtc: {report.dtc or 'not reported'}")
    if not report.readings:
        print("  no supported common freeze-frame PIDs reported")
        return
    for item in report.readings:
        print(f"  {item.name}: {item.value} {item.unit} (PID {item.pid})")


if __name__ == "__main__":
    raise SystemExit(main())
