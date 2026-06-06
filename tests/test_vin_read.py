#!/usr/bin/env python3
"""
Test script to mimic TigerTool's VIN reading sequence.
Keeps one connection open and sends all commands in sequence.
"""

import sys
import serial
import time

def send_command(ser, command, pause=0.1):
    """Send a command and read the response."""
    print(f">>> {command}")
    ser.write((command + "\r").encode('ascii'))
    time.sleep(pause)
    
    # Read response until we get the prompt
    response = ""
    while True:
        chunk = ser.read(1)
        if not chunk:
            break
        response += chunk.decode('ascii', errors='replace')
        if response.endswith('>'):
            break
    
    # Clean up response
    response = response.replace('\r', '\n').strip()
    print(f"<<< {response}")
    print()
    return response

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_vin_read.py <port>")
        print("Example: python3 test_vin_read.py /dev/cu.usbserial-XXXX")
        sys.exit(1)
    
    port = sys.argv[1]
    
    print(f"Connecting to {port}...")
    ser = serial.Serial(port, baudrate=38400, timeout=2.0)
    print("Connected!\n")
    
    try:
        # Initialization sequence (from TigerTool capture)
        print("=== INITIALIZATION ===\n")
        send_command(ser, "ATZ", pause=1.0)
        send_command(ser, "ATE0")
        send_command(ser, "ATH1")
        send_command(ser, "ATV0")
        send_command(ser, "ATL0")
        send_command(ser, "ATCAF0")
        send_command(ser, "ATCFC1")
        send_command(ser, "ATCP18")
        send_command(ser, "ATSH DA D5 F1")
        send_command(ser, "ATTP7")
        send_command(ser, "ATRV")
        
        # VIN read command
        print("=== VIN READ (03 22 F1 90) ===\n")
        response = send_command(ser, "03 22 F1 90", pause=0.5)
        
        # Check if we got data
        if "NO DATA" in response or "ERROR" in response:
            print("ERROR: No response from ECU!")
        else:
            print("SUCCESS: Got response from ECU!")
            print(f"Raw response:\n{response}\n")
            
            # Try to parse VIN
            lines = response.split('\n')
            vin_data = []
            for line in lines:
                tokens = line.split()
                for token in tokens:
                    try:
                        byte_val = int(token, 16)
                        vin_data.append(byte_val)
                    except ValueError:
                        pass
            
            if vin_data:
                print(f"Parsed bytes: {' '.join(f'{b:02X}' for b in vin_data)}")
                # Skip first 3 bytes (response header: 62 F1 90)
                if len(vin_data) > 3:
                    vin_bytes = vin_data[3:]
                    vin_text = bytes(vin_bytes).decode('ascii', errors='ignore').strip()
                    print(f"VIN: {vin_text}")
    
    finally:
        ser.close()
        print("\nConnection closed.")

if __name__ == "__main__":
    main()
