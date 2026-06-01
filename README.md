# TigerDiag v0.2.0

A macOS CLI diagnostic tool for Triumph Tiger 900 GT Pro motorcycles. Replicates TigerTool functionality using a BMDiag cable (FTDI FT232R, ELM327 v1.4) connected via USB hub.

## Features

**Currently Working:**
- ✅ Read VIN, ECU Serial, Calibration Build, Tune Number, Tune Count, Tune Date, Software Version
- ✅ Read battery voltage
- ✅ Full diagnostic scan with ECU information
- ✅ Auto-detect BMDiag/FTDI serial ports
- ✅ List available serial ports
- ✅ Send raw commands to ELM327 adapter

**In Development:**
- 🔄 Live sensor data (RPM, temperature, speed, throttle, gear, fuel level)
- 🔄 Service interval reading and reset
- 🔄 TES suspension module fault codes

**Not Yet Implemented:**
- ❌ ABS diagnostics
- ❌ TPMS diagnostics
- ❌ Throttle body balance check

## Installation

### Requirements

- macOS 10.13+
- Python 3.9+
- BMDiag cable with FTDI FT232R chip (ELM327 v1.4)
- USB hub (direct USB-C adapter does not work with Mac mini)

### Setup

```bash
# Clone the repository
git clone https://github.com/sauravnz/tiger-diag-tool-mac.git
cd tiger-diag-tool-mac

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e .
```

## Usage

### List Available Serial Ports

```bash
tigerdiag list-ports
```

### Check Connection Health

```bash
tigerdiag doctor --port /dev/cu.usbserial-ABSCDY0H
```

### Read VIN Only

```bash
tigerdiag vin --port /dev/cu.usbserial-ABSCDY0H
```

### Read ECU Information

```bash
tigerdiag ecu-info --port /dev/cu.usbserial-ABSCDY0H
tigerdiag ecu-info --port /dev/cu.usbserial-ABSCDY0H --json
```

### Full Diagnostic Scan

```bash
tigerdiag scan --port /dev/cu.usbserial-ABSCDY0H
tigerdiag scan --port /dev/cu.usbserial-ABSCDY0H --json
```

### Read Live Sensor Data

```bash
tigerdiag live --port /dev/cu.usbserial-ABSCDY0H --duration 10
```

### Read Service Interval Data

```bash
tigerdiag service --port /dev/cu.usbserial-ABSCDY0H
```

### Send Raw Commands

```bash
tigerdiag raw --port /dev/cu.usbserial-ABSCDY0H "03 22 F1 90"
```

## Technical Details

### Hardware Setup

The BMDiag cable requires a USB hub to be detected on Mac mini. Direct USB-C adapters do not work. The cable uses:
- **Chip:** FTDI FT232R (USB to serial)
- **Protocol:** ELM327 v1.4
- **Baud Rate:** 38400 bps
- **Connector:** 16-pin OBD-II

### CAN Bus Protocol

The Triumph Tiger 900 GT Pro uses ISO 15765-4 CAN with two main communication channels:

#### Engine ECU (29-bit CAN)
- **CAN Header:** DA D5 F1 (transmit), 18 DA F1 D5 (receive)
- **Protocol:** UDS Service 22 (Read Data By Identifier)
- **Baud Rate:** 500 kbps
- **DIDs Supported:**
  - F190: VIN (multi-frame ISO-TP response)
  - F18C: ECU Serial
  - F1A7: Calibration Build
  - F1A0: Tune Number
  - F1A2: Tune Count
  - F199: Tune Date (BCD encoded)
  - F1AE: Software Version

#### Instruments Module (29-bit CAN)
- **CAN Header:** DA C1 F1 (transmit), 18 DA F1 C1 (receive)
- **Protocol:** UDS Service 22 (Read Data By Identifier)
- **Status:** Partially reverse-engineered
- **Known DIDs:** Service interval data (DIDs unknown, requires further investigation)

#### Live Data (11-bit CAN)
- **Protocol:** ATTP6 (ISO 15765-4 11-bit CAN 500 kbps)
- **Transmit:** CAN ID 701
- **Receive:** CAN ID 704 (query responses), 569 (broadcast data)
- **Query Commands:**
  - 0D 01: Read odometer (returns km in bytes 3-5)
  - 47 01: Read sensor frame 2 (purpose unknown)
  - 33 64: Read sensor frame 3 (purpose unknown)

### ISO-TP Multi-Frame Response Format

```
18 DA F1 D5 10 14 62 F1 90 53 4D 54   ← First frame (10 = first, 14 = total length)
18 DA F1 D5 21 54 52 45 36 34 44 38   ← Continuation frame 1 (21 = sequence 1)
18 DA F1 D5 22 4D 41 45 34 33 30 35   ← Continuation frame 2 (22 = sequence 2)
```

**Parsing:**
1. Skip CAN frame header (18 DA F1 D5)
2. Extract ISO-TP PCI byte (first byte of remaining data)
3. For first frame (PCI 0x10): skip PCI and length, extract data from byte 2 onwards
4. For continuation frames (PCI 0x2x): skip PCI, extract data from byte 1 onwards
5. Strip 0xAA padding bytes from end

### Critical Implementation Details

**Persistent Connection:** The entire diagnostic session must use ONE persistent serial connection. Opening and closing the connection between commands causes the ELM327 to lose its configuration (CAN header, flow control settings, etc.). This was the root cause of all previous failures.

**Initialization Sequence:** All commands must be sent in this exact order within the same session:
```
ATZ → ATE0 → ATH1 → ATV0 → ATL0 → ATCAF0 → ATCFC1 → ATCP18 → ATSH DA D5 F1 → ATTP7 → ATRV
```

**Flow Control:** ATCFC1 (CAN Flow Control ON) is critical for receiving multi-frame ISO-TP responses. Without it, only the first frame is received.

## Architecture

### Core Modules

**connection.py:** Persistent serial connection to ELM327 adapter. Handles:
- Opening/closing serial port
- Sending AT commands and UDS commands
- Reading responses (including multi-frame ISO-TP)
- Triumph-specific CAN initialization

**diagnostics.py:** ECU data reading. Implements:
- UDS Service 22 (Read Data By Identifier)
- Multi-frame ISO-TP response parsing
- ECU information extraction (VIN, serial, calibration, etc.)

**live_data.py:** Real-time sensor data reading. Implements:
- 11-bit CAN protocol setup
- Live data query commands
- Sensor data parsing and formatting

**service_interval.py:** Service interval and instruments module support. Implements:
- Service interval data reading
- Service interval reset (partial - needs more reverse engineering)
- Instruments module communication

**ports.py:** Serial port detection for macOS. Auto-detects FTDI/ELM327 ports.

**cli.py:** Command-line interface with subcommands:
- list-ports, doctor, scan, vin, ecu-info, raw, live, service

## Known Limitations

1. **TES Suspension Fault:** The TES (Triumph Electronic Suspension) fault is stored in a separate suspension module, not the main engine ECU. The CAN address for this module has not yet been identified.

2. **Service Reset:** The exact command sequence for resetting the service interval has not been fully reverse-engineered from the TigerTool capture. The capture showed the instruments module returning "NO DATA" to the session control command, suggesting the bike may have been in an incorrect state.

3. **Live Data Decoding:** The raw CAN frames from live data (704 and 569) have been partially decoded. The odometer is confirmed (0D 01 query), but other sensor values (RPM, temperature, speed, etc.) require further analysis.

4. **ABS/TPMS:** These modules are not yet supported.

## Reverse Engineering Notes

### From Windows Eltima Capture (diagnosis.zip)

The terminal-view.txt file contains a complete session from TigerTool showing:

1. **ECU Read Session:** Standard UDS Service 22 queries on header DA D5 F1
2. **Instruments Session:** Attempted session control (02 10 03) on header DA C1 F1 returned NO DATA
3. **Live Data Session:** 11-bit CAN queries on CAN ID 701 with responses from 704 and 569
4. **Calibration ID:** Special query (02 09 04) on header DB 33 F1 returned calibration ID

### CAN IDs from Passive Scanning

A 10-second passive CAN bus scan identified these active CAN IDs:
- 208, 209, 210: Low-frequency messages
- 274, 275, 276, 277: Changing data (likely engine/throttle/speed)
- 500: Medium frequency
- 760: Low frequency

CAN ID 274 shows the most frequent changes and likely contains RPM, throttle, or speed data.

## Testing

### Test Scripts

Three standalone test scripts are provided for development:

```bash
# Test VIN reading with persistent connection
python3 test_vin_read.py /dev/cu.usbserial-ABSCDY0H

# Test live data reading
python3 test_live_data.py /dev/cu.usbserial-ABSCDY0H

# Passive CAN bus scanning
python3 test_can_scan.py /dev/cu.usbserial-ABSCDY0H 10
```

## Contributing

This is a reverse-engineering project. If you have:
- Windows TigerTool captures showing service reset sequences
- Information about TES suspension module CAN address
- Live data byte decoding information
- Other Triumph diagnostic protocol details

Please open an issue or contact the maintainers.

## Disclaimer

This tool communicates with your motorcycle's ECU. While it only performs read operations by default, use at your own risk. The author is not responsible for any damage to your bike or its systems.

## License

MIT License - See LICENSE file for details

## References

- [ELM327 Datasheet](https://www.elmelectronics.com/DSheets/ELM327DS.pdf)
- [ISO 14229-1 (UDS)](https://en.wikipedia.org/wiki/Unified_Diagnostic_Services)
- [ISO 15765-4 (CAN ISO-TP)](https://en.wikipedia.org/wiki/ISO_15765-2)
- [TigerTool Forum](https://www.tiger800.co.uk/)
- [Triumph Tiger Explorer Forum](https://www.tiger-explorer.com/)

## Acknowledgments

- T800XC (TigerTool author) for pioneering Triumph diagnostic tool development
- Triumph Tiger community forums for technical discussions and reverse engineering efforts
- BMDiag for the diagnostic cable hardware
