#!/usr/bin/env python3
"""
Test script to read live data from Triumph Tiger using CAN bus.

From TigerTool capture, live data uses:
- Session 3 protocol: AT TP6, AT CFC0, AT SH701, AT CRA704/569
- Commands: 0D 01, 47 01, etc.
"""

import sys
import serial
import time


def send_command(ser, command, pause=0.3):
    """Send a command and read the response."""
    ser.reset_input_buffer()
    ser.write((command + "\r").encode("ascii"))
    time.sleep(pause)

    response = ""
    deadline = time.time() + 3.0
    while time.time() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue
        response += chunk.decode("ascii", errors="replace")
        if ">" in response:
            break

    response = response.replace(">", "").replace("\r", "\n").strip()
    lines = response.split("\n")
    lines = [l.strip() for l in lines if l.strip()]
    # Remove echo
    if lines and lines[0].upper().replace(" ", "") == command.upper().replace(" ", ""):
        lines = lines[1:]
    result = "\n".join(lines)
    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_live_data.py <port>")
        sys.exit(1)

    port = sys.argv[1]
    print(f"Connecting to {port}...")
    ser = serial.Serial(port, baudrate=38400, timeout=3.0)
    print("Connected!\n")

    try:
        # === RESET ===
        print("=== RESET & INIT ===")
        resp = send_command(ser, "ATZ", pause=1.0)
        print(f"  ATZ: {resp}")

        resp = send_command(ser, "ATE0")
        print(f"  ATE0: {resp}")

        # === SESSION 1: ECU READ (verify connection) ===
        print("\n=== SESSION 1: ECU Read (verify) ===")
        send_command(ser, "ATH1")
        send_command(ser, "ATV0")
        send_command(ser, "ATL0")
        send_command(ser, "ATCAF0")
        send_command(ser, "ATCFC1")
        send_command(ser, "ATCP18")
        send_command(ser, "ATSH DA D5 F1")
        send_command(ser, "ATTP7")

        resp = send_command(ser, "ATRV")
        print(f"  Voltage: {resp}")

        resp = send_command(ser, "03 22 F1 90", pause=0.5)
        if "NO DATA" not in resp.upper():
            print(f"  VIN response: OK")
        else:
            print(f"  VIN response: NO DATA (ECU not responding)")
            print("  Aborting - ECU not ready")
            return

        # === SESSION 3: LIVE DATA ===
        print("\n=== SESSION 3: Live Data (Triumph CAN) ===")

        # Warm start to reset
        resp = send_command(ser, "ATWS", pause=1.0)
        print(f"  ATWS: {resp}")

        send_command(ser, "ATE0")
        send_command(ser, "ATTP6")
        send_command(ser, "ATH1")
        send_command(ser, "ATL0")
        send_command(ser, "ATCAF0")
        send_command(ser, "ATCFC0")  # Flow control OFF for live data
        print("  Init: OK")

        # Set transmit header and receive address
        resp = send_command(ser, "ATSH701")
        print(f"  ATSH701: {resp}")

        resp = send_command(ser, "ATCRA704")
        print(f"  ATCRA704: {resp}")

        # Try live data commands from capture
        print("\n--- Live Data Commands (Header 701, Receive 704) ---")
        commands_704 = ["0D 01", "47 01", "0D 02", "47 02", "0D 03", "47 03"]
        for cmd in commands_704:
            resp = send_command(ser, cmd, pause=0.5)
            if "NO DATA" not in resp.upper() and resp:
                print(f"  {cmd} -> {resp}")
            else:
                print(f"  {cmd} -> no data")

        # Try receive address 569
        print("\n--- Live Data Commands (Receive 569) ---")
        resp = send_command(ser, "ATCRA569")
        print(f"  ATCRA569: {resp}")

        commands_569 = ["00", "01", "02"]
        for cmd in commands_569:
            resp = send_command(ser, cmd, pause=0.5)
            if "NO DATA" not in resp.upper() and resp:
                print(f"  {cmd} -> {resp}")
            else:
                print(f"  {cmd} -> no data")

        # Try some other common Triumph addresses
        print("\n--- Trying other CAN addresses ---")
        other_addresses = ["705", "706", "700", "7DF"]
        for addr in other_addresses:
            resp = send_command(ser, f"ATCRA{addr}")
            if "OK" in resp:
                resp2 = send_command(ser, "0D 01", pause=0.5)
                if "NO DATA" not in resp2.upper() and resp2:
                    print(f"  CRA {addr}, cmd 0D01 -> {resp2}")

    finally:
        ser.close()
        print("\nConnection closed.")


if __name__ == "__main__":
    main()
