import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

from patshared import PortType

from .jack_bases import PatchEngineOuterMissing
from .patch_engine import PatchEngine
from .patch_engine_outer import PatchEngineOuter
from .port_data import PortData

_logger = logging.getLogger(__name__)

# Raw JACK port flag bits (matches jack._lib.jack_port_flags() / JackPortFlag
# in the patchbay canvas), reused here so PipeWire ports render identically.
_PORT_IS_INPUT = 0x01
_PORT_IS_OUTPUT = 0x02
_PORT_IS_PHYSICAL = 0x04
_PORT_IS_TERMINAL = 0x10


def _run(cmd: list[str], timeout: float = 2.0) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


class PipeWireEngine(PatchEngine):
    '''First-cut native PipeWire engine.

    Polls `pw-dump` for the node/port/link graph and applies connection
    changes with `pw-link`, instead of going through the JACK client API
    (which is what the default `PatchEngine` does, even under PipeWire's
    JACK-compatibility layer).

    Reduced feature set compared to the JACK engine for now: the graph is
    polled every `_poll_interval` seconds rather than streamed from live
    registry events, and there is no JACK metadata/pretty-name export,
    transport position, DSP load, or ALSA sequencer bridge support yet.

    `self.client` is intentionally left `None` for this engine's whole
    lifetime: every inherited `PatchEngine` method that touches JACK
    already checks `self.client is None` and no-ops when it is, which is
    what keeps those not-yet-implemented features quiet instead of
    crashing, without having to override each of them individually.
    '''

    def __init__(
            self, client_name: str, pretty_tmp_path: Optional[Path] = None,
            auto_export_pretty_names: bool = False):
        super().__init__(
            client_name, pretty_tmp_path, auto_export_pretty_names)
        self._poll_interval = 1.0
        self._last_poll = 0.0
        self._next_uuid = 1
        self._known_clients = set[str]()

    def start(self, patchbay_engine: PatchEngineOuter):
        self.peo = patchbay_engine
        self.peo.write_existence_file()

        if _run(['pw-dump', '--help']) is None:
            _logger.critical(
                'pw-dump not found, the PipeWire engine cannot start. '
                'Install pipewire-utils (or your distribution equivalent).')
            return

        self.jack_running = True
        self._poll_pipewire()
        self.peo.is_now_ready()

    def start_jack_client(self):
        'No JACK client to (re)start for this engine.'

    def refresh(self):
        if self.peo is None:
            raise PatchEngineOuterMissing

        self._poll_pipewire()
        self.peo.server_restarted()

    def process_patch_events(self):
        now = time.monotonic()
        if now - self._last_poll < self._poll_interval:
            return
        self._last_poll = now
        self._poll_pipewire()

    def connect_ports(
            self, port_out_name: str, port_in_name: str,
            disconnect: bool = False) -> bool:
        cmd = ['pw-link']
        if disconnect:
            cmd.append('-d')
        cmd += [port_out_name, port_in_name]
        proc = _run(cmd, timeout=3.0)
        return bool(proc is not None and proc.returncode == 0)

    def _poll_pipewire(self):
        if self.peo is None:
            raise PatchEngineOuterMissing

        proc = _run(['pw-dump'])
        if proc is None or proc.returncode != 0:
            return

        try:
            objects = json.loads(proc.stdout)
        except ValueError:
            _logger.warning(
                'pw-dump returned invalid JSON, skipping this poll')
            return

        node_names = dict[int, str]()
        for obj in objects:
            if obj.get('type') == 'PipeWire:Interface:Node':
                name = obj.get('info', {}).get('props', {}).get('node.name')
                if name:
                    node_names[obj['id']] = name

        seen_ports = dict[str, dict]()
        port_id_to_name = dict[int, str]()
        for obj in objects:
            if obj.get('type') != 'PipeWire:Interface:Port':
                continue
            info = obj.get('info', {})
            props = info.get('props', {})
            node_name = node_names.get(props.get('node.id'))
            port_name = props.get('port.name')
            if not node_name or not port_name:
                continue

            full_name = f'{node_name}:{port_name}'
            seen_ports[full_name] = {
                'is_output': info.get('direction') == 'output',
                'is_midi': 'midi' in str(props.get('format.dsp', '')).lower(),
                'physical': bool(props.get('port.physical')),
                'terminal': bool(props.get('port.terminal')),
            }
            port_id_to_name[obj['id']] = full_name

        current_clients = set(node_names.values())
        for name in current_clients - self._known_clients:
            self.peo.jack_client_added(name)
        for name in self._known_clients - current_clients:
            self.peo.jack_client_removed(name)
        self._known_clients = current_clients

        for full_name, data in seen_ports.items():
            if self.ports.from_name(full_name) is not None:
                continue
            ptype = (PortType.MIDI_JACK if data['is_midi']
                     else PortType.AUDIO_JACK)
            flags = _PORT_IS_OUTPUT if data['is_output'] else _PORT_IS_INPUT
            if data['physical']:
                flags |= _PORT_IS_PHYSICAL
            if data['terminal']:
                flags |= _PORT_IS_TERMINAL
            uuid = self._next_uuid
            self._next_uuid += 1
            self.ports.append(PortData(full_name, ptype, flags, uuid))
            self.peo.port_added(full_name, ptype, flags, uuid)

        for port_data in list(self.ports):
            if port_data.name not in seen_ports:
                self.ports.remove(port_data)
                self.peo.port_removed(port_data.name)

        seen_conns = set[tuple[str, str]]()
        for obj in objects:
            if obj.get('type') != 'PipeWire:Interface:Link':
                continue
            info = obj.get('info', {})
            out_name = port_id_to_name.get(info.get('output-port-id'))
            in_name = port_id_to_name.get(info.get('input-port-id'))
            if out_name and in_name:
                seen_conns.add((out_name, in_name))

        for conn in seen_conns:
            if conn not in self.connections:
                self.connections.append(conn)
                self.peo.connection_added(conn)

        for conn in list(self.connections):
            if conn not in seen_conns:
                self.connections.remove(conn)
                self.peo.connection_removed(conn)
