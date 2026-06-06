#!/usr/bin/env python3
"""
CAN Bus Scanner for Triumph Tiger.

Listens to all CAN traffic on the bus to discover which addresses
are broadcasting data. This helps us find RPM, speed, temperature, etc.

Uses AT MA (Monitor All) to passively listen to all CAN messages.
"""

import sys
import serial
import time
from collections import defaultdict


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_can_scan.py <port> [duration_seconds]")
        print("Example: python3 test_can_scan.py /dev/cu.usbserial-XXXX 10")
        sys.exit(1)

    port = sys.argv[1]
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    print(f"Connecting to {port}...")
    ser = serial.Serial(port, baudrate=38400, timeout=1.0)
    print("Connected!\n")

    try:
        # Reset and configure for monitoring
        ser.reset_input_buffer()
        ser.write(b"ATZ\r")
        time.sleep(1.0)
        ser.read(ser.in_waiting)

        ser.write(b"ATE0\r")
        time.sleep(0.2)
        ser.read(ser.in_waiting)

        ser.write(b"ATH1\r")
        time.sleep(0.2)
        ser.read(ser.in_waiting)

        ser.write(b"ATL0\r")
        time.sleep(0.2)
        ser.read(ser.in_waiting)

        ser.write(b"ATCAF0\r")
        time.sleep(0.2)
        ser.read(ser.in_waiting)

        # Set protocol to monitor (TP6 = ISO 15765-4 CAN 11-bit 500k)
        ser.write(b"ATTP6\r")
        time.sleep(0.2)
        ser.read(ser.in_waiting)

        print(f"Scanning CAN bus for {duration} seconds...")
        print("(Keep engine running for best results)\n")

        # Start monitoring all CAN traffic
        ser.reset_input_buffer()
        ser.write(b"ATMA\r")

        # Collect messages
        messages = defaultdict(list)
        buffer = ""
        start_time = time.time()

        while time.time() - start_time < duration:
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                buffer += chunk.decode("ascii", errors="replace")

                # Process complete lines
                while "\r" in buffer:
                    line, buffer = buffer.split("\r", 1)
                    line = line.strip()
                    if not line or line == ">" or "STOPPED" in line:
                        continue

                    # Parse CAN frame: ID DATA...
                    tokens = line.split()
                    if len(tokens) >= 2:
                        can_id = tokens[0]
                        data = " ".join(tokens[1:])
                        messages[can_id].append(data)

        # Stop monitoring
        ser.write(b"\r")
        time.sleep(0.5)
        ser.read(ser.in_waiting)

        # Print results
        print(f"\n{'=' * 60}")
        print(f"CAN Bus Scan Results ({duration} seconds)")
        print(f"{'=' * 60}")
        print(f"\nFound {len(messages)} unique CAN IDs:\n")

        # Sort by CAN ID
        for can_id in sorted(messages.keys()):
            frames = messages[can_id]
            count = len(frames)

            # Show first and last frame to see if data is changing
            first = frames[0]
            last = frames[-1]
            changing = "CHANGING" if first != last else "STATIC"

            print(f"  CAN ID: {can_id}  ({count} frames, {changing})")
            print(f"    First: {first}")
            if first != last:
                print(f"    Last:  {last}")
            print()

    except KeyboardInterrupt:
        print("\n\nScan interrupted by user.")
        ser.write(b"\r")
        time.sleep(0.3)
    finally:
        ser.close()
        print("Connection closed.")


if __name__ == "__main__":
    main()
