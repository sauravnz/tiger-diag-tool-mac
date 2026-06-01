"""
TigerDiag CLI - Diagnostic tool for Triumph Tiger motorcycles on macOS.

Commands:
    tigerdiag scan       - Full diagnostic scan (ECU info + DTCs)
    tigerdiag vin        - Read VIN only
    tigerdiag ecu-info   - Read ECU information
    tigerdiag doctor     - Check connection health
    tigerdiag list-ports - List available serial ports
    tigerdiag raw        - Send raw command to adapter
"""

import argparse
import json
import sys
from typing import Optional

from .connection import Connection, ConnectionError, NoDataError
from .diagnostics import read_ecu_info, read_calibration_id, run_full_diagnostic
from .ports import find_likely_port, list_ports


def main():
    parser = argparse.ArgumentParser(
        prog="tigerdiag",
        description="Diagnostic CLI for Triumph Tiger motorcycles on macOS",
    )
    subparsers = parser.add_subparsers(dest="command")

    # list-ports
    sp_ports = subparsers.add_parser("list-ports", help="List available serial ports")

    # doctor
    sp_doctor = subparsers.add_parser("doctor", help="Check connection health")
    sp_doctor.add_argument("--port", help="Serial port path")

    # scan
    sp_scan = subparsers.add_parser("scan", help="Full diagnostic scan")
    sp_scan.add_argument("--port", help="Serial port path")
    sp_scan.add_argument("--json", action="store_true", help="Output as JSON")

    # vin
    sp_vin = subparsers.add_parser("vin", help="Read VIN from ECU")
    sp_vin.add_argument("--port", help="Serial port path")

    # ecu-info
    sp_ecu = subparsers.add_parser("ecu-info", help="Read ECU information")
    sp_ecu.add_argument("--port", help="Serial port path")
    sp_ecu.add_argument("--json", action="store_true", help="Output as JSON")

    # raw
    sp_raw = subparsers.add_parser("raw", help="Send raw command")
    sp_raw.add_argument("--port", help="Serial port path")
    sp_raw.add_argument("command_str", metavar="COMMAND", help="Command to send")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "list-ports":
        cmd_list_ports()
    elif args.command == "doctor":
        cmd_doctor(args.port)
    elif args.command == "scan":
        cmd_scan(args.port, args.json)
    elif args.command == "vin":
        cmd_vin(args.port)
    elif args.command == "ecu-info":
        cmd_ecu_info(args.port, args.json)
    elif args.command == "raw":
        cmd_raw(args.port, args.command_str)


def _resolve_port(port: Optional[str]) -> str:
    """Resolve port: use provided or auto-detect."""
    if port:
        return port
    detected = find_likely_port()
    if not detected:
        print("error: No ELM327/FTDI serial port detected.")
        print("       Use --port to specify manually, or run 'tigerdiag list-ports'.")
        sys.exit(1)
    return detected


def cmd_list_ports():
    """List available serial ports."""
    ports = list_ports()
    if not ports:
        print("No serial ports found.")
        return
    for port_info in ports:
        print(f"  {port_info['device']}  {port_info['description']}")


def cmd_doctor(port: Optional[str]):
    """Check connection health."""
    print("TigerDiag Doctor")
    print("=" * 40)
    print()

    # List ports
    ports = list_ports()
    print("Serial ports:")
    for p in ports:
        print(f"  {p['device']}  {p['description']}")
    print()

    # Try to connect
    port = _resolve_port(port)
    print(f"Connecting to {port}...")

    try:
        with Connection(port) as conn:
            info = conn.initialize()
            print(f"  Adapter: {info['identity']}")
            print(f"  Voltage: {info['voltage']}")
            print()

            # Try to read VIN as ECU probe
            vin = conn.read_did_ascii("F190")
            if vin:
                print(f"  ECU probe: OK")
                print(f"  VIN: {vin}")
            else:
                print(f"  ECU probe: no response to VIN read")
            print()
            print("Result: Connection successful!")

    except ConnectionError as e:
        print(f"  Connection FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"  Error: {e}")
        sys.exit(1)


def cmd_scan(port: Optional[str], as_json: bool):
    """Full diagnostic scan."""
    port = _resolve_port(port)

    try:
        with Connection(port) as conn:
            report = run_full_diagnostic(conn)

            if as_json:
                _print_scan_json(report)
            else:
                _print_scan_text(report)

    except ConnectionError as e:
        print(f"error: {e}")
        sys.exit(1)


def cmd_vin(port: Optional[str]):
    """Read VIN only."""
    port = _resolve_port(port)

    try:
        with Connection(port) as conn:
            conn.initialize()
            vin = conn.read_did_ascii("F190")
            if vin:
                print(f"VIN: {vin}")
            else:
                print("VIN: not available")

    except ConnectionError as e:
        print(f"error: {e}")
        sys.exit(1)


def cmd_ecu_info(port: Optional[str], as_json: bool):
    """Read ECU information."""
    port = _resolve_port(port)

    try:
        with Connection(port) as conn:
            conn.initialize()
            info = read_ecu_info(conn)

            if as_json:
                print(json.dumps({
                    "vin": info.vin,
                    "ecu_serial": info.ecu_serial,
                    "calibration_build": info.calibration_build,
                    "tune_number": info.tune_number,
                    "tune_count": info.tune_count,
                    "tune_date": info.tune_date,
                    "software_version": info.software_version,
                    "voltage": info.voltage,
                }, indent=2))
            else:
                print("ECU Information")
                print("=" * 40)
                print(f"  VIN:               {info.vin or 'not available'}")
                print(f"  ECU Serial:        {info.ecu_serial or 'not available'}")
                print(f"  Calibration Build: {info.calibration_build or 'not available'}")
                print(f"  Tune Number:       {info.tune_number or 'not available'}")
                print(f"  Tune Count:        {info.tune_count or 'not available'}")
                print(f"  Tune Date:         {info.tune_date or 'not available'}")
                print(f"  Software Version:  {info.software_version or 'not available'}")
                print(f"  Battery Voltage:   {info.voltage or 'not available'}")

    except ConnectionError as e:
        print(f"error: {e}")
        sys.exit(1)


def cmd_raw(port: Optional[str], command_str: str):
    """Send raw command to adapter."""
    port = _resolve_port(port)

    try:
        with Connection(port) as conn:
            conn.initialize()
            try:
                response = conn.send(command_str, pause=0.5)
                print(response)
            except NoDataError:
                print(f"no data")

    except ConnectionError as e:
        print(f"error: {e}")
        sys.exit(1)


def _print_scan_text(report):
    """Print scan report in human-readable format."""
    print("TigerDiag Scan Report")
    print("=" * 40)
    print()

    # Adapter info
    print("Adapter:")
    for key, value in report.adapter_info.items():
        print(f"  {key}: {value}")
    print()

    # ECU info
    if report.ecu_info:
        print("ECU Information:")
        info = report.ecu_info
        print(f"  VIN:               {info.vin or 'not available'}")
        print(f"  ECU Serial:        {info.ecu_serial or 'not available'}")
        print(f"  Calibration Build: {info.calibration_build or 'not available'}")
        print(f"  Tune Number:       {info.tune_number or 'not available'}")
        print(f"  Tune Count:        {info.tune_count or 'not available'}")
        print(f"  Tune Date:         {info.tune_date or 'not available'}")
        print(f"  Software Version:  {info.software_version or 'not available'}")
        print(f"  Battery Voltage:   {info.voltage or 'not available'}")
    else:
        print("ECU Information: not available")
    print()

    # DTCs
    if report.dtcs:
        print("Diagnostic Trouble Codes:")
        for dtc in report.dtcs:
            print(f"  {dtc.code}  {dtc.description}")
    else:
        print("Diagnostic Trouble Codes: none")
    print()

    # Errors
    if report.error:
        print(f"Errors: {report.error}")


def _print_scan_json(report):
    """Print scan report as JSON."""
    data = {
        "adapter": report.adapter_info,
        "ecu_info": None,
        "dtcs": [],
        "connected": report.connected,
        "error": report.error,
    }

    if report.ecu_info:
        info = report.ecu_info
        data["ecu_info"] = {
            "vin": info.vin,
            "ecu_serial": info.ecu_serial,
            "calibration_build": info.calibration_build,
            "tune_number": info.tune_number,
            "tune_count": info.tune_count,
            "tune_date": info.tune_date,
            "software_version": info.software_version,
            "voltage": info.voltage,
        }

    if report.dtcs:
        data["dtcs"] = [{"code": d.code, "description": d.description} for d in report.dtcs]

    print(json.dumps(data, indent=2))
