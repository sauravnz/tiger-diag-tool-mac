# TigerDiag

TigerDiag is a macOS-friendly diagnostic CLI for a Triumph Tiger 900 GT Pro using an ELM327-compatible USB serial adapter such as the BMDiag v1.4 OBD interface cable.

It currently focuses on the safe, standard diagnostic path:

- find likely macOS serial ports for FTDI/USB OBD adapters
- initialise an ELM327-compatible interface
- read adapter identity and voltage
- read VIN when the ECU exposes it through standard OBD-II
- read MIL status and DTC count
- read and decode stored, pending, and permanent OBD-II trouble codes
- read a common live sensor snapshot for context such as voltage, coolant temperature, RPM, MAP, throttle, and fuel trims
- read standard OBD freeze-frame data for the conditions captured when a fault was stored
- run read-only UDS module DTC scans against configured CAN diagnostic headers
- clear engine/emissions DTCs with an explicit confirmation flag
- send raw ELM/OBD/UDS commands for controlled investigation

TigerTool V3.0 publicly documents support for Tiger 800, 900, Sport, and Explorer/1200 models, including DTC read/clear and service interval reset, over ELM327 serial interfaces. Its public instructions do not publish the proprietary Triumph service reset command bytes, so TigerDiag does not guess them. Proprietary write actions are only available through explicit local JSON profiles and require an extra risk flag.

## Setup on macOS

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Plug the BMDiag cable into the bike and your Mac. Turn the ignition on and set the kill switch to run. The engine does not need to be running for normal DTC scans.

List candidate ports:

```sh
tigerdiag list-ports
```

Run the setup doctor before the first scan. It separates serial-port detection, ELM adapter response, and ECU response:

```sh
tigerdiag doctor
```

Run a full scan. If you know the port, pass it explicitly:

```sh
tigerdiag scan --port /dev/cu.usbserial-XXXX
```

Or let TigerDiag try likely ports and common ELM baud rates:

```sh
tigerdiag scan
```

If auto protocol does not connect, try the later Tiger/CAN profile first:

```sh
tigerdiag scan --protocol can_11_500
```

For a modern Tiger, follow the standard OBD scan with the read-only CAN/UDS module scan. This asks configured modules for DTCs using UDS service `19 02` and does not clear or write anything:

```sh
tigerdiag module-scan --port /dev/cu.usbserial-XXXX
```

Save JSON output from the first real bike run so the module headers can be refined:

```sh
tigerdiag scan --port /dev/cu.usbserial-XXXX --json > standard-scan.json
tigerdiag scan --port /dev/cu.usbserial-XXXX --snapshot --freeze-frame --json > standard-scan-with-context.json
tigerdiag module-scan --port /dev/cu.usbserial-XXXX --json > module-scan.json
tigerdiag analyze --standard standard-scan-with-context.json --modules module-scan.json
```

Or run the whole capture in one command:

```sh
tigerdiag collect --port /dev/cu.usbserial-XXXX --protocol can_11_500
tigerdiag collect --port /dev/cu.usbserial-XXXX --protocol can_11_500 --discover-modules
```

`collect` creates a timestamped folder under `reports/` containing `doctor.json`, `standard-scan.json`, `module-scan.json`, `summary.txt`, and `report.html`. If the adapter or ECU is not reachable, it still saves `doctor.json`, `summary.txt`, and a connection-focused `report.html`. With `--discover-modules`, it also saves `discovered-modules.json` and, when usable headers are found, `discovered-module-profile.json`.

TigerDiag reassembles ISO-TP multi-frame CAN responses, which matters for longer VIN responses and module DTC replies containing several faults.

For older ECUs, ISO9141-2 may be worth trying:

```sh
tigerdiag scan --protocol iso9141
```

## Commands

```sh
tigerdiag list-ports
tigerdiag doctor
tigerdiag doctor --port /dev/cu.usbserial-XXXX --protocol can_11_500
tigerdiag adapter-info --port /dev/cu.usbserial-XXXX
tigerdiag scan --port /dev/cu.usbserial-XXXX
tigerdiag scan --port /dev/cu.usbserial-XXXX --json
tigerdiag scan --port /dev/cu.usbserial-XXXX --snapshot --json
tigerdiag scan --port /dev/cu.usbserial-XXXX --snapshot --freeze-frame --json
tigerdiag snapshot --port /dev/cu.usbserial-XXXX
tigerdiag snapshot --port /dev/cu.usbserial-XXXX --pid 42 --pid 05 --json
tigerdiag freeze-frame --port /dev/cu.usbserial-XXXX --json
tigerdiag module-scan --port /dev/cu.usbserial-XXXX
tigerdiag module-scan --port /dev/cu.usbserial-XXXX --json
tigerdiag module-scan --port /dev/cu.usbserial-XXXX --header 7E0 --header 760
tigerdiag discover-modules --port /dev/cu.usbserial-XXXX --protocol can_11_500 --start-header 700 --end-header 7EF --json
tigerdiag profile-from-discovery --discovery discovered-modules.json --output profiles/my-tiger-modules.json
tigerdiag analyze --standard standard-scan.json --modules module-scan.json
tigerdiag compare --before-standard before/standard-scan.json --before-modules before/module-scan.json --after-standard after/standard-scan.json --after-modules after/module-scan.json
tigerdiag collect --port /dev/cu.usbserial-XXXX --protocol can_11_500
tigerdiag collect --port /dev/cu.usbserial-XXXX --protocol can_11_500 --discover-modules
tigerdiag clear-dtcs --port /dev/cu.usbserial-XXXX --yes
tigerdiag raw --port /dev/cu.usbserial-XXXX "0100"
tigerdiag raw --port /dev/cu.usbserial-XXXX --header 7E0 --show-headers "1902FF"
tigerdiag service-reset --profile profiles/service-reset.example.json --dry-run --set next_service_date=2026-10-01 --set distance_km=10000
tigerdiag service-reset --profile profiles/service-reset.example.json --i-understand-risk
```

## Diagnostic Workflow

1. Connect the cable to the bike first, then to the Mac.
2. Turn ignition on and set the kill switch to run. Leave the engine off for DTC scans.
3. Run `tigerdiag list-ports` and note the `/dev/cu.usbserial...` port.
4. Run the doctor:

```sh
tigerdiag doctor --port /dev/cu.usbserial-XXXX --protocol can_11_500
```

If `doctor` says the adapter is not connected, the Mac is not talking to the ELM cable. Check the USB cable, macOS serial permission/driver state, adapter power, and baud rate.

If `doctor` says the adapter is OK but the ECU probe is not ready, the USB serial side works. Check ignition on, kill switch run, the OBD connector seating, and try `--protocol can_11_500` before falling back to `--protocol auto`.

5. Capture a standard OBD report with a sensor snapshot and freeze-frame data:

```sh
tigerdiag scan --port /dev/cu.usbserial-XXXX --snapshot --freeze-frame --json > standard-scan.json
```

The snapshot includes supported common PIDs such as control module voltage, coolant temperature, engine RPM, intake manifold pressure, throttle position, and fuel trims. Freeze-frame data asks the ECU for the stored mode 02 context around a recorded fault. These values help the analyzer flag clues like weak voltage or large fuel-trim corrections.

6. Capture a read-only module report:

```sh
tigerdiag module-scan --port /dev/cu.usbserial-XXXX --json > module-scan.json
```

7. Convert both captures into an actionable summary:

```sh
tigerdiag analyze --standard standard-scan.json --modules module-scan.json
```

The analyzer ranks safety-critical chassis/ABS and confirmed module faults above generic engine codes, includes the module source where available, and prints next inspection steps. It is intentionally conservative: it suggests battery, ground, connector, sensor, and subsystem checks before clearing codes.

After a repair or a code clear, capture another report and compare:

```sh
tigerdiag compare \
  --before-standard reports/before/standard-scan.json \
  --before-modules reports/before/module-scan.json \
  --after-standard reports/after/standard-scan.json \
  --after-modules reports/after/module-scan.json
```

The comparison groups findings into resolved, persistent, and new. Persistent or new findings should be diagnosed before clearing codes again.

For normal use, `collect` is easier than the manual sequence:

```sh
tigerdiag collect --port /dev/cu.usbserial-XXXX --protocol can_11_500
open reports
```

Open the newest `report.html` in Safari or Chrome for a readable summary. `collect` includes live snapshot and freeze-frame context in `standard-scan.json`. Keep the JSON files as the evidence bundle; they are what we use to refine module headers and troubleshoot any parsing gaps.

For a first deeper bike-mapping session, add discovery:

```sh
tigerdiag collect \
  --port /dev/cu.usbserial-XXXX \
  --protocol can_11_500 \
  --discover-modules
```

That saves discovery output inside the same report folder. If responding module headers are found, it also writes `discovered-module-profile.json`, which can be passed back to `collect --profile`.

## Module Scan Profiles

The default module profile is [profiles/tiger-900-readonly-modules.json](profiles/tiger-900-readonly-modules.json). It starts with standard CAN powertrain headers and a few read-only candidates for ABS, instruments, and chassis/TPMS. These candidate headers are not claimed to be final Triumph documentation; they are a controlled discovery profile so the first garage sessions can show which modules actually answer on your Tiger 900 GT Pro.

If a module responds with `NO DATA`, leave the result in the JSON capture. That tells us which headers are wrong or unsupported. If a module returns raw lines beginning with a positive UDS response such as `59 02`, TigerDiag will decode the DTC/status records.

If the default profile misses dash warnings, run read-only header discovery:

```sh
tigerdiag discover-modules \
  --port /dev/cu.usbserial-XXXX \
  --protocol can_11_500 \
  --start-header 700 \
  --end-header 7EF \
  --json > discovered-modules.json
```

Discovery sends UDS `19 02 FF` read-DTC requests only. It records headers that answer with a positive response, a UDS negative response, or another raw response. Use those responding headers to update the module profile for your actual Tiger.

Generate a reusable profile from discovery output:

```sh
tigerdiag profile-from-discovery \
  --discovery discovered-modules.json \
  --output profiles/my-tiger-modules.json
```

Then run module scans or collections with the generated profile:

```sh
tigerdiag module-scan --port /dev/cu.usbserial-XXXX --profile profiles/my-tiger-modules.json
tigerdiag collect --port /dev/cu.usbserial-XXXX --profile profiles/my-tiger-modules.json
```

## Service Reset

Resetting the Tiger service reminder is not a standard OBD-II function. TigerTool can do it, but the public TigerTool documents describe the workflow rather than the proprietary diagnostic command sequence.

TigerDiag includes a guarded `service-reset` command that can execute a local JSON command profile only when you pass `--i-understand-risk`. The included example profile is intentionally empty. This is the right place to add verified commands later, either from manufacturer documentation or your own serial capture of TigerTool talking to the bike.

Service profiles can include variables such as `{next_service_date}` and `{distance_km}`. Always dry-run a profile first:

```sh
tigerdiag service-reset \
  --profile profiles/service-reset.example.json \
  --dry-run \
  --set next_service_date=2026-10-01 \
  --set distance_km=10000
```

Only a profile with verified commands should ever be sent to the bike:

```sh
tigerdiag service-reset \
  --profile profiles/verified-service-reset.json \
  --port /dev/cu.usbserial-XXXX \
  --set next_service_date=2026-10-01 \
  --set distance_km=10000 \
  --i-understand-risk
```

On newer Tigers with calendar-based service reminders, TigerTool V3.0 notes that it resets the distance interval but not the due date; the date may still need to be updated manually from the bike's instrument menu.

Useful evidence paths for implementing service reset later:

- official Triumph diagnostic documentation for the Tiger 900 instrument/service interval routine
- a serial/CAN capture of TigerTool performing a successful service reset on the exact bike generation
- a known-good command sequence confirmed on the same ECU/instrument generation, added to a local profile and reviewed before use

Publicly available TigerTool and forum material found so far describes the workflow and supported models, but not the raw command sequence. Recent Tiger 900 service reminder discussions also point at instrument-system behavior and commercial diagnostic tools rather than published ELM command bytes, so TigerDiag keeps this as a verified-profile feature rather than sending guessed writes.

## Safety

Reading DTCs is low risk. Clearing DTCs and any proprietary write command can erase useful diagnostic evidence and may affect ECU adaptation until the bike relearns. Always record the scan output before clearing codes, and investigate active faults rather than treating the clear button as the fix.

The `module-scan` command is read-only. The only built-in write action is `clear-dtcs`, which requires `--yes`. Proprietary service reset profiles require `--i-understand-risk` and are intentionally empty until verified command bytes are available.

## Research Notes

- TigerTool V3.0 instructions list Tiger 900 support and features including service interval reset, DTC read/clear, ABS DTC read/clear, ABS bleed, throttle balance, TPMS, VIN, ECU serial, and tune reference.
- TigerTool V3.0 documents ELM327 USB/Bluetooth use over ISO9141-2 and ISO15765-4/CAN, and notes that weak clone adapters can fail basic ELM commands such as `AT D`.
- TigerTool V3.0 says the service interval for Tiger 800, 900, and Sport models is limited to 6000 miles or 10000 km, and that newer calendar due dates are not reset by TigerTool.

Sources:

- [TigerTool V3.0 Instructions, BMDiag](https://www.bmdiag.co.uk/user/tiger%20tool/TigerTool%20V3.0%20Instructions.pdf)
- [TigerTool V2.0 Instructions](https://www.triumph-tiger.cz/media/kunena/attachments/157/TigerToolV2.0Instructions.pdf)
