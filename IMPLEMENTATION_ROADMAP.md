# TigerDiag Implementation Roadmap

## Current Status: v0.2.0

**Architecture:** Persistent connection with working ECU communication
**Last Updated:** June 1, 2026
**Branch:** fixes

## Phase 1: Foundation ✅ COMPLETE

### Objectives
- Establish persistent connection architecture
- Reverse engineer TigerTool CAN initialization sequence
- Successfully read VIN and ECU information

### Completed
- ✅ Persistent `Connection` class in `connection.py`
- ✅ ISO-TP multi-frame response parsing
- ✅ UDS Service 22 (Read Data By Identifier) implementation
- ✅ VIN reading (DID F190)
- ✅ ECU Serial reading (DID F18C)
- ✅ Calibration Build, Tune Number, Tune Count, Tune Date, Software Version
- ✅ Battery voltage reading
- ✅ CLI with `doctor` and `scan` commands
- ✅ Auto-port detection for macOS

### Key Files
- `src/tigerdiag/connection.py` — Core persistent connection
- `src/tigerdiag/diagnostics.py` — ECU data reading
- `src/tigerdiag/cli.py` — Command-line interface

### Lessons Learned
- **Critical:** ELM327 loses configuration when connection is closed/reopened
- **Critical:** ATCFC1 (CAN Flow Control ON) is required for multi-frame responses
- **Important:** Must use exact TigerTool initialization sequence in correct order

---

## Phase 2: Live Data ⏳ IN PROGRESS

### Objectives
- Implement live sensor data reading
- Decode CAN frames 704 and 569
- Support real-time monitoring

### Current Status
- ✅ Live data module structure (`live_data.py`)
- ✅ 11-bit CAN protocol setup (ATTP6)
- ✅ Odometer reading confirmed (0D 01 query)
- ✅ CLI `live` command implemented
- ⏳ Sensor byte decoding (RPM, temperature, speed, throttle, gear, fuel)
- ⏳ Broadcast data parsing (CAN ID 569)

### Remaining Work

#### 2.1: Decode Live Data Bytes
**Priority:** HIGH
**Effort:** Medium

From terminal capture:
```
Query "0D 01" → Response "704 8D 01 00 47 B5 00 00 00"
  Confirmed: Bytes 3-5 = 0x0047B5 = 18357 km (matches TigerTool screenshot)
  
Query "47 01" → Response "704 C7 02 00 01 00 00 01 FF"
  Unknown: What does each byte represent?
  
Broadcast "569 08 00 40 22 01 2A 01 00"
  Unknown: What are these values?
  Note: First byte changes (08 vs 0A) - possibly sequence counter
```

**Investigation Method:**
1. Request user to capture live data while:
   - Revving engine (to identify RPM bytes)
   - Varying throttle (to identify throttle bytes)
   - Riding at different speeds (to identify speed bytes)
2. Correlate byte changes with known sensor values
3. Implement decoding functions in `live_data.py`

**Expected Outcome:**
- `decode_live_frame_704()` function
- `decode_broadcast_569()` function
- Full sensor data in `LiveDataFrame` dataclass

#### 2.2: Continuous Live Data Monitoring
**Priority:** MEDIUM
**Effort:** Low

Extend `read_live_data()` to:
- Display real-time updates in terminal
- Format as table or graph
- Support different output formats (JSON, CSV)

---

## Phase 3: Service Interval ⏳ IN PROGRESS

### Objectives
- Read service interval data from instruments module
- Implement service interval reset
- Support service due date and distance tracking

### Current Status
- ✅ Service interval module structure (`service_interval.py`)
- ✅ Instruments module header (DA C1 F1) identified
- ✅ CLI `service` command implemented
- ⏳ Service interval reading (DIDs unknown)
- ⏳ Service interval reset (command sequence unknown)

### Remaining Work

#### 3.1: Reverse Engineer Service Interval DIDs
**Priority:** HIGH
**Effort:** High

From TigerTool screenshot (Insts tab):
```
Current ODO: 18357 km
Last service: 000000 km, Date 01/01/24
Service due: 000000 km, Date 01/01/24
Distance to service: 10000 km
Time to next service: 365 days
```

**What we need to find:**
- DID for current odometer (likely F1B0 or similar)
- DID for last service odometer (F1B1?)
- DID for last service date (F1B2?)
- DID for service due odometer (F1B3?)
- DID for service due date (F1B4?)
- DID for distance to service (F1B5?)
- DID for days to service (F1B6?)

**Investigation Method:**
1. Request user to capture TigerTool session with Eltima monitor
2. Look for UDS Service 22 queries on header DA C1 F1
3. Extract the DID values and response formats
4. Implement in `read_service_interval()`

**Expected Outcome:**
- Complete list of service interval DIDs
- `read_service_interval()` function working
- Service data displayed in human-readable format

#### 3.2: Implement Service Interval Reset
**Priority:** HIGH
**Effort:** High

From terminal capture, attempted reset:
```
ATSH DA C1 F1
02 10 03 → NO DATA
```

The `02 10 03` is UDS DiagnosticSessionControl (Extended Session), but it returned NO DATA.

**What we need to find:**
- Does the instruments module require a different session setup?
- What is the actual service reset command? (Likely UDS Service 2E - Write Data By Identifier)
- What DIDs need to be written?
- What are the new values to write?

**Investigation Method:**
1. Request user to perform service reset in TigerTool while capturing with Eltima
2. Specifically capture the moment they click "Reset" button
3. Extract the exact byte sequence sent
4. Implement in `reset_service_interval()`

**Expected Outcome:**
- `reset_service_interval()` function working
- Safe implementation with dry-run option
- Confirmation message showing new service interval

---

## Phase 4: TES Suspension Module ⏳ NOT STARTED

### Objectives
- Find TES suspension module CAN address
- Read suspension fault codes
- Display TES system status

### Current Status
- ❌ Module address unknown
- ❌ Protocol unknown
- ❌ Fault code format unknown

### Background
User sees "CHECK MANUAL" on dashboard with suspension icon, but TigerTool shows 0 DTCs in engine ECU. This means:
- TES has its own separate module
- TES faults are not stored in the main engine ECU
- Need to communicate with suspension module separately

### Remaining Work

#### 4.1: Identify TES Module CAN Address
**Priority:** HIGH
**Effort:** Medium

**Investigation Method:**
1. Perform passive CAN bus scan while TES fault is active
2. Look for new CAN IDs that appear when TES is active
3. Try UDS Service 19 (Read DTC) on suspected addresses
4. Correlate with TigerTool behavior

**Suspected Addresses:**
- 29-bit CAN: DA C3 F1 (pattern: DA XX F1)
- 29-bit CAN: DA C5 F1
- 11-bit CAN: 7E2 (standard OBD DTC address)

**Expected Outcome:**
- Confirmed TES module CAN address
- Protocol identified (likely UDS)
- DTC format documented

#### 4.2: Read TES Fault Codes
**Priority:** HIGH
**Effort:** Low (once address is found)

Once the module address is identified, use standard UDS Service 19:
```
19 02 F1 00 → Read DTC status
```

**Expected Outcome:**
- `read_tes_dtcs()` function
- Display TES fault codes in `scan` command
- CLI `tes` command for TES diagnostics

#### 4.3: TES System Information
**Priority:** MEDIUM
**Effort:** Medium

Read TES-specific information:
- Suspension mode (Road/Rally/Sport)
- Preload setting
- Damping setting
- Fault history

---

## Phase 5: ABS & TPMS Support ⏳ NOT STARTED

### Objectives
- Read ABS diagnostic codes
- Read TPMS sensor data
- Display ABS/TPMS status

### Current Status
- ❌ Not implemented

### Remaining Work
- Identify ABS module CAN address
- Identify TPMS module CAN address
- Implement UDS communication
- Add CLI commands

---

## Phase 6: Documentation & Polish ⏳ IN PROGRESS

### Objectives
- Comprehensive documentation
- User-friendly error messages
- Example captures and guides

### Current Status
- ✅ README.md with protocol details
- ✅ AGENTS.md with developer guide
- ✅ LIVE_DATA_AND_NEXT_STEPS.md from previous session
- ⏳ Troubleshooting guide
- ⏳ Example output and screenshots
- ⏳ Video tutorial

### Remaining Work
- Create troubleshooting guide for common issues
- Add example output for each command
- Document how to capture Eltima sessions
- Create video tutorial for setup and usage

---

## Testing Strategy

### Unit Testing
- Test `_parse_isotp_response()` with known frames
- Test DID parsing functions
- Test CAN frame decoding

### Integration Testing
- Test with actual bike (requires access)
- Test with different ELM327 adapters
- Test with different macOS versions

### Regression Testing
- Ensure existing commands still work after changes
- Test on both `main` (stable) and `fixes` (development) branches

---

## Risk Assessment

### High Risk
- **Service Reset:** Destructive operation, could affect bike if wrong command is sent
  - Mitigation: Implement dry-run mode, require explicit confirmation
- **TES Module:** Unknown protocol, could cause issues if wrong commands sent
  - Mitigation: Read-only operations first, test thoroughly

### Medium Risk
- **Live Data Decoding:** Incorrect byte interpretation could show wrong values
  - Mitigation: Validate against known values (odometer already confirmed)
- **Multi-frame Responses:** Could lose data if ISO-TP parsing is incorrect
  - Mitigation: Extensive testing with known DIDs

### Low Risk
- **Port Detection:** Could detect wrong port on systems with many serial devices
  - Mitigation: User can specify port manually

---

## Success Criteria

### Phase 2 (Live Data) Complete When:
- ✅ All sensor bytes decoded and validated
- ✅ Live data command works reliably
- ✅ User can see real-time RPM, temperature, speed, etc.

### Phase 3 (Service Interval) Complete When:
- ✅ Service interval data reads correctly
- ✅ Service reset command implemented and tested
- ✅ User can reset service interval from CLI

### Phase 4 (TES) Complete When:
- ✅ TES module CAN address identified
- ✅ TES fault codes can be read
- ✅ User sees TES fault in `scan` output

### Overall Project Complete When:
- ✅ All major features implemented
- ✅ Comprehensive documentation
- ✅ Tested on multiple Tiger 900 models
- ✅ Ready for public release

---

## Dependencies & Blockers

### Blocking Phase 2 (Live Data)
- Need user to capture live data with known sensor values
- Need correlation data (RPM, temperature, speed while capturing)

### Blocking Phase 3 (Service Interval)
- Need user to capture service reset session from TigerTool
- Need Eltima Serial Port Monitor on Windows (user has this)

### Blocking Phase 4 (TES)
- Need user to trigger TES fault and capture CAN traffic
- Need to identify TES module CAN address

---

## Timeline Estimate

- **Phase 2 (Live Data):** 2-3 days (blocked on user capture)
- **Phase 3 (Service Interval):** 2-3 days (blocked on user capture)
- **Phase 4 (TES):** 1-2 days (blocked on user capture)
- **Phase 5 (ABS/TPMS):** 3-5 days
- **Phase 6 (Documentation):** 1-2 days

**Total:** 2-3 weeks (assuming user captures are available)

---

## Next Immediate Steps

1. **For User:** Capture TigerTool sessions with Eltima while:
   - Reading live data (engine running, varying RPM/speed/throttle)
   - Resetting service interval
   - Triggering TES fault (if possible)

2. **For Developer:** Prepare to parse captures and implement:
   - Live data byte decoding
   - Service interval reset command
   - TES module discovery

3. **For Testing:** Set up test environment with:
   - Bike connected and ready
   - Eltima monitor running
   - TigerDiag CLI ready to test

---

## References

- TigerTool Author: T800XC (https://www.tiger-explorer.com/index.php?action=profile;u=56)
- Tiger Explorer Forum: https://www.tiger-explorer.com/
- Tiger 800 Forum: https://www.tiger800.co.uk/
- ELM327 Datasheet: https://www.elmelectronics.com/DSheets/ELM327DS.pdf
- ISO 14229-1 (UDS): Unified Diagnostic Services
- ISO 15765-4 (CAN ISO-TP): CAN Transport Protocol
