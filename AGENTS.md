# TigerDiag Agent Instructions

This document provides guidance for future AI agents working on the TigerDiag project.

## Project Overview

TigerDiag is a macOS CLI diagnostic tool for Triumph Tiger 900 GT Pro motorcycles. It replicates TigerTool functionality by communicating with the bike's ECU via a BMDiag cable (FTDI FT232R, ELM327 v1.4) connected to a USB hub.

**Current Status:** v0.2.0 - Persistent connection architecture working, VIN/ECU info reading confirmed, live data and service interval modules implemented.

## Critical Architecture Decision

**PERSISTENT CONNECTION IS ESSENTIAL:** The entire diagnostic session must use ONE persistent serial connection. Opening and closing the connection between commands causes the ELM327 to lose its configuration (CAN header, flow control settings, etc.). This was the root cause of all previous failures and must be maintained in all future work.

## Key Files

### Core Implementation
- `src/tigerdiag/connection.py` — Persistent serial connection class (DO NOT MODIFY LIGHTLY)
- `src/tigerdiag/diagnostics.py` — ECU data reading (VIN, serial, calibration, etc.)
- `src/tigerdiag/live_data.py` — Live sensor data reading (11-bit CAN protocol)
- `src/tigerdiag/service_interval.py` — Service interval and instruments module
- `src/tigerdiag/cli.py` — Command-line interface
- `src/tigerdiag/ports.py` — Serial port detection for macOS

### Reference Materials
- `README.md` — Complete documentation with protocol details
- `LIVE_DATA_AND_NEXT_STEPS.md` — Previous session findings
- `test_vin_read.py` — Standalone VIN reading proof-of-concept
- `test_live_data.py` — Live data testing script
- `test_can_scan.py` — Passive CAN bus scanner

### Archive (DO NOT MODIFY)
- `not-working/` — Old broken code from previous architecture attempts

## CAN Bus Protocol Reference

### Engine ECU (29-bit CAN)
```
Header: DA D5 F1 (transmit), 18 DA F1 D5 (receive)
Protocol: UDS Service 22 (Read Data By Identifier)
DIDs:
  F190 = VIN
  F18C = ECU Serial
  F1A7 = Calibration Build
  F1A0 = Tune Number
  F1A2 = Tune Count
  F199 = Tune Date (BCD: 0x22 0x05 0x18 = 2022-05-18)
  F1AE = Software Version
```

### Instruments Module (29-bit CAN)
```
Header: DA C1 F1 (transmit), 18 DA F1 C1 (receive)
Protocol: UDS Service 22 (Read Data By Identifier)
Status: Partially reverse-engineered
DIDs: Unknown (service interval data)
```

### Live Data (11-bit CAN)
```
Protocol: ATTP6 (ISO 15765-4 11-bit CAN 500 kbps)
Transmit: CAN ID 701
Receive: CAN ID 704 (query responses), 569 (broadcast)
Queries:
  0D 01 → Odometer (bytes 3-5 = km value)
  47 01 → Sensor frame 2 (purpose unknown)
  33 64 → Sensor frame 3 (purpose unknown)
```

### ISO-TP Multi-Frame Response Parsing
```
First frame:  18 DA F1 D5 10 14 62 F1 90 ...  (PCI 0x10 = first, 0x14 = length)
Cont frame 1: 18 DA F1 D5 21 ...              (PCI 0x21 = sequence 1)
Cont frame 2: 18 DA F1 D5 22 ...              (PCI 0x22 = sequence 2)

Parsing:
1. Skip CAN header (18 DA F1 D5)
2. Extract PCI byte (first byte of remaining)
3. For first frame (0x10): skip PCI+length, extract data from byte 2
4. For cont frames (0x2x): skip PCI, extract data from byte 1
5. Strip 0xAA padding from end
```

## Known Issues & Limitations

### TES Suspension Fault
The TES (Triumph Electronic Suspension) fault is stored in a separate suspension module, not the main engine ECU. The CAN address for this module is unknown. The user sees "CHECK MANUAL" on the dashboard with a suspension icon, but TigerTool shows 0 DTCs in the engine ECU.

**Investigation needed:**
- Find the suspension module CAN address (likely 29-bit)
- Determine if it uses UDS or a different protocol
- Identify the DTC/fault code format

### Service Reset
The exact command sequence for resetting the service interval has not been fully reverse-engineered. The Windows Eltima capture (diagnosis.zip) showed:
- Header: DA C1 F1 (instruments module)
- Command: 02 10 03 (UDS Extended Diagnostic Session)
- Response: NO DATA (module did not respond)

This suggests either:
1. The bike was in the wrong state (ignition off, engine off, etc.)
2. The service reset uses a different approach than shown in the capture
3. The module requires a different session setup

**Next steps:**
- Request user to capture a complete service reset session from TigerTool
- Analyze the exact byte sequence sent when clicking "Reset" button
- Implement UDS Service 2E (Write Data By Identifier) for service interval DIDs

### Live Data Decoding
Odometer reading is confirmed (0D 01 query). Other sensor values (RPM, temperature, speed, throttle, gear, fuel level) need decoding:
- Raw frame from 704: `8D 01 00 47 B5 00 00 00`
- Raw frame from 569: `08 00 40 22 01 2A 01 00` or `0A 00 40 22 01 2A 01 00`

**Investigation needed:**
- Correlate frame bytes with known sensor values
- Rev engine while capturing to identify RPM bytes
- Check temperature sensor correlation
- Identify speed/throttle bytes

## Testing

### Manual Testing Procedure
1. Connect BMDiag cable to bike via USB hub
2. Turn on ignition (engine off)
3. Run: `tigerdiag doctor --port /dev/cu.usbserial-XXXX`
4. If successful, try: `tigerdiag scan --port /dev/cu.usbserial-XXXX`
5. For live data: `tigerdiag live --port /dev/cu.usbserial-XXXX --duration 10`

### Test Scripts
- `test_vin_read.py` — Standalone VIN test (good for debugging connection issues)
- `test_live_data.py` — Live data capture and analysis
- `test_can_scan.py` — Passive CAN bus monitoring

## Git Workflow

- **Branch:** `fixes` (development branch)
- **Main:** `main` (stable backup)
- **Commit message format:** Clear, descriptive, with bullet points for changes

Example:
```
Add TES suspension module support

- Implement tes_module.py with UDS DTC reading
- Add 'tes' CLI command
- Update README with TES protocol details
- Test on 2021 Tiger 900 GT Pro
```

## Future Work Priority

1. **High Priority:**
   - Decode live data sensor bytes (RPM, temperature, speed)
   - Find TES suspension module CAN address
   - Reverse engineer complete service reset sequence

2. **Medium Priority:**
   - Implement ABS diagnostics
   - Implement TPMS diagnostics
   - Add throttle body balance check

3. **Low Priority:**
   - GUI interface (currently CLI only)
   - Windows support (currently macOS only)
   - Bluetooth adapter support (currently USB only)

## Resources

- **TigerTool Forums:** https://www.tiger800.co.uk/ and https://www.tiger-explorer.com/
- **T800XC (TigerTool author):** https://www.tiger-explorer.com/index.php?action=profile;u=56
- **ELM327 Datasheet:** https://www.elmelectronics.com/DSheets/ELM327DS.pdf
- **ISO 14229-1 (UDS):** Unified Diagnostic Services standard
- **ISO 15765-4 (CAN ISO-TP):** CAN transport protocol standard

## Contact & Support

For questions about the project, refer to:
- README.md for general information
- LIVE_DATA_AND_NEXT_STEPS.md for previous session findings
- The test scripts for working code examples
- The archived `not-working/` folder for context on what was tried before
