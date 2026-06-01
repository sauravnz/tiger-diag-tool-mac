"""
Lightweight browser GUI for TigerDiag.

This serves a local web UI from Python's standard library. It keeps one
persistent serial connection in the server process and keeps write operations
behind explicit allowlists and confirmations.
"""

import argparse
import json
import threading
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from typing import Any, Dict, Optional

from .connection import Connection, NoDataError
from .diagnostics import read_ecu_info
from .live_data import format_live_data, read_live_frame, setup_live_data_session
from .ports import find_likely_port, list_ports
from .service_interval import (
    SERVICE_RESET_DATE_2027_06_01_COMMAND,
    SERVICE_RESET_DISTANCE_10000KM_COMMAND,
    format_service_interval,
    read_service_interval,
    reset_service_date_2027_06_01_captured,
    reset_service_distance_10000km_captured,
)


HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TigerDiag</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f6f7f8;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #64707d;
      --line: #d6dbe1;
      --accent: #0b6bcb;
      --danger: #b42318;
      --ok: #067647;
      --code: #111827;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #171a1f;
        --panel: #20242b;
        --text: #edf0f3;
        --muted: #aab3bd;
        --line: #363c45;
        --accent: #67aaf9;
        --danger: #ff8a80;
        --ok: #7ad9a8;
        --code: #0f1318;
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header, main { max-width: 1180px; margin: 0 auto; padding: 14px; }
    header {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      align-items: center;
      border-bottom: 1px solid var(--line);
    }
    h1 { margin: 0; font-size: 21px; font-weight: 650; }
    button, select, input {
      height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--text);
      padding: 0 10px;
      font: inherit;
    }
    button { cursor: pointer; }
    button.primary { background: var(--accent); border-color: var(--accent); color: white; }
    button.danger { border-color: var(--danger); color: var(--danger); }
    button:disabled { opacity: .5; cursor: not-allowed; }
    .bar, .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .status {
      min-width: 190px;
      padding: 7px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--muted);
      text-align: right;
    }
    .tabs { display: flex; gap: 6px; margin: 12px 0; border-bottom: 1px solid var(--line); }
    .tab {
      border-bottom-left-radius: 0;
      border-bottom-right-radius: 0;
      border-bottom-color: transparent;
    }
    .tab.active { background: var(--panel); color: var(--accent); border-color: var(--line); border-bottom-color: var(--panel); }
    section { display: none; }
    section.active { display: block; }
    .grid { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }
    .panel h2 { margin: 0 0 10px; font-size: 15px; }
    pre {
      min-height: 280px;
      margin: 10px 0 0;
      padding: 12px;
      overflow: auto;
      border-radius: 6px;
      background: var(--code);
      color: #f8fafc;
      white-space: pre-wrap;
    }
    .log { min-height: 360px; max-height: 520px; }
    .hint { color: var(--muted); margin: 8px 0; }
    .safety {
      display: grid;
      gap: 8px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      margin-top: 10px;
    }
    .subpanel {
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }
    .subpanel h2 { margin: 0 0 10px; font-size: 15px; }
    label { color: var(--text); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    @media (max-width: 880px) {
      header { grid-template-columns: 1fr; }
      .grid { grid-template-columns: 1fr; }
      .status { text-align: left; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>TigerDiag</h1>
      <div class="hint">Persistent Mac diagnostic session for Triumph Tiger</div>
    </div>
    <div class="bar">
      <select id="port"></select>
      <button id="refresh">Refresh</button>
      <button id="connect" class="primary">Connect</button>
      <button id="disconnect">Disconnect</button>
      <div id="status" class="status">Disconnected</div>
    </div>
  </header>

  <main>
    <div class="tabs">
      <button class="tab active" data-tab="ecu">ECU</button>
      <button class="tab" data-tab="service">Service</button>
      <button class="tab" data-tab="live">Live</button>
      <button class="tab" data-tab="raw">Raw</button>
    </div>

    <div class="grid">
      <div>
        <section id="ecu" class="active panel">
          <h2>ECU Data</h2>
          <button id="readEcu">Show Cached ECU Info</button>
          <pre id="ecuOut"></pre>
        </section>

        <section id="service" class="panel">
          <h2>Service Data</h2>
          <button id="readService">Show Cached Service Data</button>
          <pre id="serviceOut"></pre>
          <div class="subpanel">
            <h2>Captured TigerTool Reset Commands</h2>
            <div class="mono">Distance reset, 10000 km: __DISTANCE_COMMAND__</div>
            <div class="mono">Date reset, captured 2027-06-01: __DATE_COMMAND__</div>
            <div class="safety">
              <label><input id="ack" type="checkbox"> I understand this sends a write command captured from TigerTool.</label>
              <label>Type RESET <input id="resetText" class="mono" autocomplete="off"></label>
              <div class="row">
                <button id="resetDistance" class="danger">Reset Distance 10000 km</button>
                <button id="resetDate" class="danger">Reset Date Captured</button>
              </div>
            </div>
          </div>
        </section>

        <section id="live" class="panel">
          <h2>Live Data</h2>
          <div class="row">
            <button id="startLive" class="primary">Start Live Capture</button>
            <button id="stopLive">Stop Live Capture</button>
            <button id="readLive">Show Last Live Frame</button>
          </div>
          <div class="hint">Start this only when the engine is running. Stop it before switching back to normal diagnostics.</div>
          <pre id="liveOut"></pre>
        </section>

        <section id="raw" class="panel">
          <h2>Raw Command</h2>
          <div class="row">
            <input id="rawCommand" class="mono" value="03 22 F1 90" style="flex:1; min-width: 240px;">
            <button id="sendRaw">Send</button>
          </div>
          <div class="hint">Adapter commands and read requests are allowed. Other raw commands require the service write safety unlock.</div>
          <pre id="rawOut"></pre>
        </section>
      </div>

      <aside class="panel">
        <h2>Session Log</h2>
        <pre id="log" class="log"></pre>
      </aside>
    </div>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    const log = (text) => {
      const target = $("log");
      const time = new Date().toLocaleTimeString();
      target.textContent += `[${time}] ${text}\\n`;
      target.scrollTop = target.scrollHeight;
    };
    const setStatus = (text) => $("status").textContent = text;
    const safety = () => ({ ack: $("ack").checked, resetText: $("resetText").value });
    let snapshot = null;

    function renderSnapshot(nextSnapshot) {
      snapshot = nextSnapshot || snapshot;
      if (!snapshot) return;
      $("ecuOut").textContent = snapshot.ecu?.text || "";
      $("serviceOut").textContent = snapshot.service?.text || "";
      $("liveOut").textContent = snapshot.live?.text || "";
    }

    let liveTimer = null;

    async function api(path, body, quiet = false) {
      if (!quiet) setStatus("Working...");
      const response = await fetch(path, {
        method: body ? "POST" : "GET",
        headers: body ? { "Content-Type": "application/json" } : {},
        body: body ? JSON.stringify(body) : undefined
      });
      const data = await response.json();
      if (data.log) data.log.forEach(log);
      if (!data.ok) {
        if (!quiet) setStatus("Error");
        log(`ERROR: ${data.error || "Request failed"}`);
        throw new Error(data.error || "Request failed");
      }
      setStatus(data.status || "Ready");
      return data;
    }

    async function refreshPorts() {
      const data = await api("/api/ports");
      const select = $("port");
      select.textContent = "";
      data.ports.forEach((port) => {
        const option = document.createElement("option");
        option.value = port.device;
        option.textContent = `${port.device} - ${port.description || "n/a"}`;
        select.appendChild(option);
      });
      if (data.likely && [...select.options].some((o) => o.value === data.likely)) {
        select.value = data.likely;
      }
      log(`Found ${data.ports.length} serial ports`);
    }

    document.querySelectorAll(".tab").forEach((button) => {
      button.addEventListener("click", () => {
        document.querySelectorAll(".tab, section").forEach((el) => el.classList.remove("active"));
        button.classList.add("active");
        $(button.dataset.tab).classList.add("active");
      });
    });

    $("refresh").onclick = refreshPorts;
    $("connect").onclick = async () => {
      if (liveTimer) clearInterval(liveTimer);
      liveTimer = null;
      const data = await api("/api/connect", { port: $("port").value });
      renderSnapshot(data.snapshot);
      setStatus(data.status);
    };
    $("disconnect").onclick = async () => {
      if (liveTimer) clearInterval(liveTimer);
      liveTimer = null;
      await api("/api/disconnect");
      snapshot = null;
      $("ecuOut").textContent = "";
      $("serviceOut").textContent = "";
      $("liveOut").textContent = "";
    };
    $("readEcu").onclick = async () => $("ecuOut").textContent = (await api("/api/read-ecu")).text;
    $("readService").onclick = async () => $("serviceOut").textContent = (await api("/api/read-service")).text;
    $("readLive").onclick = async () => $("liveOut").textContent = (await api("/api/read-live")).text;
    $("startLive").onclick = async () => {
      const data = await api("/api/live-start", {});
      $("liveOut").textContent = data.text || "";
      if (liveTimer) clearInterval(liveTimer);
      liveTimer = setInterval(async () => {
        try {
          const frame = await api("/api/live-poll", null, true);
          $("liveOut").textContent = frame.text || "";
        } catch (_) {
          clearInterval(liveTimer);
          liveTimer = null;
        }
      }, 1000);
    };
    $("stopLive").onclick = async () => {
      if (liveTimer) clearInterval(liveTimer);
      liveTimer = null;
      const data = await api("/api/live-stop", {});
      $("liveOut").textContent = data.text || $("liveOut").textContent;
    };
    $("sendRaw").onclick = async () => {
      const command = $("rawCommand").value.trim();
      if (!command) return;
      if (!confirm(`Send raw command?\\n\\n${command}`)) return;
      const data = await api("/api/raw", { command, ...safety() });
      $("rawOut").textContent += `>>> ${command}\\n${data.response}\\n\\n`;
    };
    $("resetDistance").onclick = async () => {
      if (!confirm("Send captured TigerTool distance reset command?")) return;
      await api("/api/reset", { kind: "distance", ...safety() });
    };
    $("resetDate").onclick = async () => {
      if (!confirm("Send captured TigerTool date reset command?")) return;
      await api("/api/reset", { kind: "date", ...safety() });
    };

    refreshPorts().catch(() => {});
  </script>
</body>
</html>
"""


class TigerDiagState:
    def __init__(self):
        self.lock = threading.RLock()
        self.conn: Optional[Connection] = None
        self.port: Optional[str] = None
        self.snapshot: Optional[Dict[str, Any]] = None
        self.live_active = False
        self.live_frames = []

    def status(self) -> str:
        if self.live_active:
            return f"Live capture active: {self.port or self.conn.port}"
        if self.snapshot:
            if self.snapshot.get("bike_connected"):
                return f"Snapshot ready: {self.snapshot.get('port')}"
            return f"Adapter connected, bike not responding: {self.snapshot.get('port')}"
        if self.conn and self.conn.is_open:
            return f"Connected: {self.conn.port}"
        return "Disconnected"

    def require_conn(self) -> Connection:
        if not self.conn or not self.conn.is_open:
            raise RuntimeError("Connect to the bike first.")
        return self.conn

    def require_snapshot(self) -> Dict[str, Any]:
        if not self.snapshot:
            raise RuntimeError("Connect first to capture a diagnostic snapshot.")
        return self.snapshot

    def connect(self, port: str) -> Dict[str, Any]:
        if not port:
            raise RuntimeError("Select a serial port first.")
        with self.lock:
            if self.conn and self.conn.is_open:
                self.conn.close()
            self.snapshot = None
            self.live_active = False
            self.live_frames = []
            self.port = port
            conn = Connection(port)
            try:
                conn.open()
                adapter_info = conn.initialize()
            except Exception:
                conn.close()
                raise
            self.conn = conn
            self.snapshot = capture_diagnostic_snapshot(conn, port, adapter_info)
            return self.snapshot

    def disconnect(self) -> None:
        with self.lock:
            if self.conn:
                self.conn.close()
            self.conn = None
            self.snapshot = None
            self.live_active = False
            self.live_frames = []

    def reset_with_fresh_connection(self, kind: str, log) -> bool:
        port = self.port or (self.conn.port if self.conn else None)
        if not port:
            raise RuntimeError("Connect first so the reset port is known.")

        if self.conn:
            self.conn.close()
            self.conn = None
        self.snapshot = None
        self.live_active = False
        self.live_frames = []

        reset_conn = Connection(port)
        try:
            log(f"Opening fresh reset connection: {port}")
            reset_conn.open()
            if kind == "distance":
                return reset_service_distance_10000km_captured(reset_conn, log=log)
            if kind == "date":
                return reset_service_date_2027_06_01_captured(reset_conn, log=log)
            raise RuntimeError("Unknown reset kind.")
        finally:
            reset_conn.close()

    def start_live_capture(self) -> str:
        with self.lock:
            conn = self.require_conn()
            if not setup_live_data_session(conn):
                raise RuntimeError("Failed to set up live data session.")
            self.live_active = True
            self.live_frames = []
            text = "Live capture started. Start or keep the engine running, then watch frames update here."
            if self.snapshot:
                self.snapshot["live"] = {"text": text, "data": {"frames": []}}
            return text

    def poll_live_capture(self) -> Dict[str, Any]:
        with self.lock:
            conn = self.require_conn()
            if not self.live_active:
                raise RuntimeError("Live capture is not running.")
            frame = read_live_frame(conn)
            frame_data = _live_frame_to_dict(frame)
            self.live_frames.append(frame_data)
            text = (
                f"Live capture active\n"
                f"Frames captured: {len(self.live_frames)}\n\n"
                f"{format_live_data(frame)}"
            )
            if self.snapshot:
                self.snapshot["live"] = {
                    "text": text,
                    "data": {
                        "latest": frame_data,
                        "frames": self.live_frames,
                    },
                }
            return {"text": text, "data": frame_data, "count": len(self.live_frames)}

    def stop_live_capture(self) -> str:
        with self.lock:
            if not self.live_active:
                return self.snapshot.get("live", {}).get("text", "Live capture is not running.") if self.snapshot else "Live capture is not running."
            self.live_active = False
            try:
                if self.conn and self.conn.is_open:
                    self.conn.initialize()
            finally:
                text = f"Live capture stopped. Frames captured: {len(self.live_frames)}"
                if self.snapshot:
                    live = self.snapshot.setdefault("live", {"text": "", "data": {}})
                    live["text"] = text + ("\n\n" + live["text"] if live.get("text") else "")
                    live.setdefault("data", {})["frames"] = self.live_frames
                return text


def _raw_command_is_read_only(command: str) -> bool:
    normalized = " ".join(command.upper().split())
    tokens = normalized.split()
    if not tokens:
        return True
    if tokens[0].startswith("AT"):
        return True
    if normalized in {"00", "0D 01", "47 01"}:
        return True
    if tokens[0] in {"01", "02", "03", "09"}:
        return True
    if len(tokens) >= 2 and tokens[1] in {"19", "22"}:
        return True
    return False


def _safety_unlocked(payload: Dict[str, Any]) -> bool:
    return bool(payload.get("ack")) and str(payload.get("resetText", "")).strip().upper() == "RESET"


def _format_ecu_info_data(info, voltage: Optional[str]) -> str:
    lines = [
        f"VIN: {info.vin or 'not available'}",
        f"ECU Serial: {info.ecu_serial or 'not available'}",
        f"Calibration Build: {info.calibration_build or 'not available'}",
        f"Tune Number: {info.tune_number or 'not available'}",
        f"Tune Count: {info.tune_count if info.tune_count is not None else 'not available'}",
        f"Tune Date: {info.tune_date or 'not available'}",
        f"Software Version: {info.software_version or 'not available'}",
        f"Battery Voltage: {voltage or 'not available'}",
    ]
    return "\n".join(lines)


def _live_frame_to_dict(frame) -> Dict[str, Any]:
    data = asdict(frame)
    if frame.raw_704 is not None:
        data["raw_704"] = frame.raw_704.hex().upper()
    if frame.raw_569 is not None:
        data["raw_569"] = frame.raw_569.hex().upper()
    return data


def capture_diagnostic_snapshot(conn: Connection, port: str, adapter_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    Capture all read-only GUI data immediately after connection.

    The Tiger/ELM327 session is sensitive to reconfiguration, so the GUI tabs read
    from this in-memory JSON-style snapshot instead of issuing fresh commands.
    """
    errors = []

    try:
        ecu_info = read_ecu_info(conn)
        ecu_text = _format_ecu_info_data(ecu_info, conn.voltage)
        ecu_data = asdict(ecu_info)
    except Exception as exc:
        errors.append(f"ECU read failed: {exc}")
        ecu_text = f"ECU read failed: {exc}"
        ecu_data = {}

    try:
        service_data = read_service_interval(conn)
        service_text = format_service_interval(service_data)
        service_json = asdict(service_data)
    except Exception as exc:
        errors.append(f"Service read failed: {exc}")
        service_text = f"Service read failed: {exc}"
        service_json = {}

    live_text = "Live capture not started. Start the engine, then click Start Live Capture."
    live_json = {"frames": []}

    return {
        "port": port,
        "adapter": adapter_info,
        "bike_connected": bool(ecu_data.get("vin")),
        "ecu": {"text": ecu_text, "data": ecu_data},
        "service": {"text": service_text, "data": service_json},
        "live": {"text": live_text, "data": live_json},
        "errors": errors,
    }


def create_handler(state: TigerDiagState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/" or self.path.startswith("/?"):
                self._send_html()
                return
            if self.path == "/api/ports":
                self._send_json({
                    "ok": True,
                    "ports": list_ports(),
                    "likely": find_likely_port(),
                    "status": state.status(),
                })
                return
            if self.path == "/api/status":
                self._send_json({"ok": True, "status": state.status()})
                return
            if self.path == "/api/snapshot":
                self._send_snapshot_json()
                return
            if self.path == "/api/read-ecu":
                self._send_snapshot_text("ecu")
                return
            if self.path == "/api/read-service":
                self._send_snapshot_text("service")
                return
            if self.path == "/api/read-live":
                self._send_snapshot_text("live")
                return
            if self.path == "/api/live-poll":
                self._send_live_poll()
                return
            self.send_error(404)

        def do_POST(self):
            payload = self._read_json()
            log = []
            try:
                if self.path == "/api/connect":
                    snapshot = state.connect(str(payload.get("port", "")))
                    log.extend([
                        f"Opening {payload.get('port', '')}",
                        f"Adapter: {snapshot.get('adapter', {}).get('identity')}",
                        f"Voltage: {snapshot.get('adapter', {}).get('voltage')}",
                        "Bike ECU: OK" if snapshot.get("bike_connected") else "Bike ECU: NOT RESPONDING",
                        "Snapshot captured; tab data is now loaded from cached JSON.",
                    ])
                    for error in snapshot.get("errors", []):
                        log.append(error)
                    self._send_json({"ok": True, "status": state.status(), "snapshot": snapshot, "log": log})
                    return

                if self.path == "/api/disconnect":
                    state.disconnect()
                    self._send_json({"ok": True, "status": state.status(), "log": ["Disconnected"]})
                    return

                if self.path == "/api/live-start":
                    text = state.start_live_capture()
                    self._send_json({
                        "ok": True,
                        "status": state.status(),
                        "text": text,
                        "log": ["Live capture started"],
                    })
                    return

                if self.path == "/api/live-stop":
                    text = state.stop_live_capture()
                    self._send_json({
                        "ok": True,
                        "status": state.status(),
                        "text": text,
                        "log": ["Live capture stopped"],
                    })
                    return

                if self.path in {"/api/read-ecu", "/api/read-service", "/api/read-live"}:
                    snapshot = state.require_snapshot()
                    if self.path == "/api/read-ecu":
                        self._send_json({"ok": True, "status": state.status(), "text": snapshot["ecu"]["text"]})
                        return

                    if self.path == "/api/read-service":
                        self._send_json({"ok": True, "status": state.status(), "text": snapshot["service"]["text"]})
                        return

                    if self.path == "/api/read-live":
                        self._send_json({"ok": True, "status": state.status(), "text": snapshot["live"]["text"]})
                        return

                with state.lock:
                    conn = state.require_conn()

                    if self.path == "/api/raw":
                        if state.live_active:
                            raise RuntimeError("Stop live capture before sending raw commands.")
                        command = str(payload.get("command", "")).strip()
                        if not command:
                            raise RuntimeError("Command is required.")
                        if not _raw_command_is_read_only(command) and not _safety_unlocked(payload):
                            raise RuntimeError("Raw command is locked because it is not recognized as read-only.")
                        log.append(f">>> {command}")
                        try:
                            response = conn.send(command, pause=0.5)
                        except NoDataError:
                            response = "NO DATA"
                        log.append(f"<<< {response}")
                        self._send_json({"ok": True, "status": state.status(), "response": response, "log": log})
                        return

                    if self.path == "/api/reset":
                        if not _safety_unlocked(payload):
                            raise RuntimeError('Check the safety box and type "RESET" first.')
                        kind = str(payload.get("kind", ""))
                        ok = state.reset_with_fresh_connection(kind, log.append)
                        log.append("Reset acknowledged by bike" if ok else "Reset did not receive expected acknowledgement")
                        log.append("Reset connection closed; reconnect to capture a fresh diagnostic snapshot.")
                        self._send_json({"ok": ok, "status": state.status(), "log": log})
                        return

                self.send_error(404)
            except Exception as exc:
                self._send_json({"ok": False, "status": state.status(), "error": str(exc), "log": log}, status=400)

        def _send_html(self):
            html = (
                HTML_TEMPLATE
                .replace("__DISTANCE_COMMAND__", SERVICE_RESET_DISTANCE_10000KM_COMMAND)
                .replace("__DATE_COMMAND__", SERVICE_RESET_DATE_2027_06_01_COMMAND)
            )
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_snapshot_json(self):
            try:
                snapshot = state.require_snapshot()
                self._send_json({"ok": True, "status": state.status(), "snapshot": snapshot})
            except Exception as exc:
                self._send_json({"ok": False, "status": state.status(), "error": str(exc)}, status=400)

        def _send_snapshot_text(self, key: str):
            try:
                snapshot = state.require_snapshot()
                self._send_json({"ok": True, "status": state.status(), "text": snapshot[key]["text"]})
            except Exception as exc:
                self._send_json({"ok": False, "status": state.status(), "error": str(exc)}, status=400)

        def _send_live_poll(self):
            try:
                frame = state.poll_live_capture()
                self._send_json({
                    "ok": True,
                    "status": state.status(),
                    "text": frame["text"],
                    "data": frame["data"],
                    "count": frame["count"],
                })
            except Exception as exc:
                self._send_json({"ok": False, "status": state.status(), "error": str(exc)}, status=400)

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            return json.loads(raw.decode("utf-8"))

        def _send_json(self, payload: Dict[str, Any], status: int = 200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return Handler


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> str:
    TCPServer.allow_reuse_address = True
    state = TigerDiagState()
    server = ThreadingHTTPServer((host, port), create_handler(state))
    url = f"http://{host}:{server.server_port}/"
    if open_browser:
        webbrowser.open(url)
    print(f"TigerDiag GUI running at {url}")
    print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.disconnect()
        server.server_close()
    return url


def main():
    parser = argparse.ArgumentParser(description="Start the TigerDiag browser GUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    run_server(args.host, args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
