#!/usr/bin/env python3
"""Small LAN-only administration panel for the Minecraft server.

The panel deliberately has no framework or cloud dependency. It talks to the
Minecraft container through RCON on the private Compose network and uses a
control file for the one operation that needs a clean container restart:
resetting the world.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import socket
import struct
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


HOST = os.getenv("ADMIN_HOST", "0.0.0.0")
PORT = int(os.getenv("ADMIN_PORT", "8090"))
RCON_HOST = os.getenv("RCON_HOST", "minecraft")
RCON_PORT = int(os.getenv("RCON_PORT", "25575"))
RCON_PASSWORD = os.environ["RCON_PASSWORD"]
CONTROL_DIR = Path(os.getenv("CONTROL_DIR", "/control"))
RESET_REQUEST = CONTROL_DIR / "reset-request"

reset_lock = threading.Lock()
resetting = False
last_reset_message = ""

PLAYER_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")
SEED_RE = re.compile(r"^-?[A-Za-z0-9_-]{1,64}$")
ITEM_RE = re.compile(r"^(?:[a-z0-9_.-]+:)?[a-z0-9_./-]{1,96}$")
COORDINATES_RE = re.compile(r"\[\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\]")
STRUCTURE_COORDINATES_RE = re.compile(r"\[\s*(-?\d+)\s*,\s*~\s*,\s*(-?\d+)\s*\]")


class RconError(RuntimeError):
    pass


class RconClient:
    SERVERDATA_AUTH = 3
    SERVERDATA_EXECCOMMAND = 2

    def __init__(self, host: str, port: int, password: str) -> None:
        self.host = host
        self.port = port
        self.password = password

    def command(self, command: str) -> str:
        request_id = secrets.randbelow(2_000_000_000) + 1
        with socket.create_connection((self.host, self.port), timeout=3.0) as connection:
            connection.settimeout(3.0)
            self._send(connection, request_id, self.SERVERDATA_AUTH, self.password)
            auth_id, _, _ = self._receive(connection)
            if auth_id == -1:
                raise RconError("RCON authentication failed")

            self._send(connection, request_id, self.SERVERDATA_EXECCOMMAND, command)
            parts: list[str] = []
            response_id, _, payload = self._receive(connection)
            if response_id in (request_id, -1):
                parts.append(payload.decode("utf-8", "replace"))

            # Minecraft normally sends one RCON response.  Read any immediately
            # available continuation packets without imposing the former three
            # second timeout on every dashboard refresh.
            connection.settimeout(0.05)
            try:
                while True:
                    response_id, _, payload = self._receive(connection)
                    if response_id not in (request_id, -1):
                        continue
                    parts.append(payload.decode("utf-8", "replace"))
            except socket.timeout:
                pass
            return "".join(parts).strip()

    @staticmethod
    def _send(connection: socket.socket, request_id: int, packet_type: int, body: str) -> None:
        encoded = body.encode("utf-8") + b"\x00\x00"
        length = 4 + 4 + len(encoded)
        connection.sendall(struct.pack("<iii", length, request_id, packet_type) + encoded)

    @staticmethod
    def _receive(connection: socket.socket) -> tuple[int, int, bytes]:
        raw_length = RconClient._read_exact(connection, 4)
        (length,) = struct.unpack("<i", raw_length)
        if length < 10 or length > 1_048_576:
            raise RconError("invalid RCON packet length")
        packet = RconClient._read_exact(connection, length)
        request_id, packet_type = struct.unpack("<ii", packet[:8])
        return request_id, packet_type, packet[8:-2]

    @staticmethod
    def _read_exact(connection: socket.socket, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = connection.recv(remaining)
            if not chunk:
                raise RconError("RCON connection closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


rcon = RconClient(RCON_HOST, RCON_PORT, RCON_PASSWORD)


def request_body(handler: BaseHTTPRequestHandler) -> bytes:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as error:
        raise ValueError("invalid content length") from error
    if length <= 0 or length > 16_384:
        raise ValueError("request body too large")
    return handler.rfile.read(length)


def form_value(body: bytes, name: str) -> str:
    values = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).get(name, [""])
    return values[0].strip()


def validate_player(value: str) -> str:
    if not PLAYER_RE.fullmatch(value):
        raise ValueError("nom de joueur invalide")
    return value


def validate_seed(value: str) -> str:
    if not SEED_RE.fullmatch(value):
        raise ValueError("seed invalide")
    return value


def resolve_seed(value: str) -> str:
    requested = value.strip().lower()
    if requested in {"", "random", "aleatoire", "aléatoire"}:
        # Keep the value compatible with Minecraft's signed long seed range.
        return str(secrets.randbits(63) - (1 << 62))
    return validate_seed(value)


def validate_item(value: str) -> str:
    item = value.lower()
    if not ITEM_RE.fullmatch(item):
        raise ValueError("identifiant d'item invalide")
    return item if ":" in item else "minecraft:" + item


def validate_amount(value: str) -> int:
    try:
        amount = int(value)
    except ValueError as error:
        raise ValueError("quantité invalide") from error
    if amount < 1 or amount > 64:
        raise ValueError("la quantité doit être entre 1 et 64")
    return amount


def players_from_list(output: str) -> list[str]:
    if ":" not in output:
        return []
    names = output.rsplit(":", 1)[1].strip()
    return [name.strip() for name in names.split(",") if name.strip()]


def server_snapshot() -> dict[str, Any]:
    try:
        players_output = rcon.command("list")
        seed_output = rcon.command("seed")
        seed_match = re.search(r"-?\d+", seed_output)
        return {
            "online": True,
            "players": players_from_list(players_output),
            "seed": seed_match.group(0) if seed_match else "inconnue",
            "resetting": resetting,
        }
    except (OSError, RconError) as error:
        return {
            "online": False,
            "players": [],
            "seed": "hors ligne",
            "resetting": resetting,
            "error": str(error),
        }


def write_reset_request(seed: str) -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CONTROL_DIR / f"reset-request.{os.getpid()}.tmp"
    temporary.write_text(
        f"seed={seed}\nrequested_at={int(time.time())}\n",
        encoding="utf-8",
    )
    os.replace(temporary, RESET_REQUEST)


def reset_worker(seed: str) -> None:
    global resetting, last_reset_message
    try:
        for _ in range(120):
            time.sleep(2)
            snapshot = server_snapshot()
            if not snapshot["online"]:
                continue
            # A plains village guarantees both requested properties at spawn:
            # a prairie and a village immediately around the starting point.
            village_output = rcon.command("locate structure minecraft:village_plains")
            village = STRUCTURE_COORDINATES_RE.search(village_output)
            if village is not None:
                x, z = (int(value) for value in village.groups())
                # Vanilla finds a safe spawn position around the requested
                # world spawn; 80 is above ordinary plains-village terrain.
                rcon.command(f"setworldspawn {x} 80 {z}")
                last_reset_message = f"Monde prêt : seed {seed}, village de prairie au spawn ({x}, {z})."
                return

            # Extremely defensive fallback for unusual world generation.
            locate_output = rcon.command("locate biome minecraft:plains")
            plains = COORDINATES_RE.search(locate_output)
            if plains is not None:
                x, y, z = (int(value) for value in plains.groups())
                rcon.command(f"setworldspawn {x} {y} {z}")
                last_reset_message = f"Monde prêt : seed {seed}, spawn prairie en ({x}, {y}, {z})."
                return
            last_reset_message = "Nouveau monde en ligne, localisation du village de prairie en cours..."
        last_reset_message = "Le monde a redémarré, mais la préparation du spawn a dépassé le délai."
    except (OSError, RconError) as error:
        last_reset_message = f"Le monde a redémarré, préparation incomplète : {error}"
    finally:
        resetting = False


def html_escape(value: object) -> str:
    text = str(value)
    return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
    )


def status_fragment() -> str:
    snapshot = server_snapshot()
    state = "En ligne" if snapshot["online"] else "Hors ligne / redémarrage"
    state_class = "ok" if snapshot["online"] else "warn"
    player_names = snapshot["players"]
    players_html = "".join(
        f'''<li><strong>{html_escape(name)}</strong>
          <form hx-post="/actions/op" hx-target="#action-result" hx-swap="innerHTML">
            <input type="hidden" name="player" value="{html_escape(name)}">
            <button type="submit">rendre admin</button>
          </form>
        </li>'''
        for name in player_names
    )
    if not players_html:
        players_html = "<li class=muted>Aucun joueur connecté</li>"
    reset_html = html_escape(last_reset_message) if last_reset_message else "Prêt."
    return f"""
    <div class="status-grid">
      <div><span>Serveur</span><strong class="{state_class}">{html_escape(state)}</strong></div>
      <div><span>Seed</span><strong>{html_escape(snapshot['seed'])}</strong></div>
      <div><span>Joueurs</span><strong>{len(player_names)}</strong></div>
    </div>
    <p class="status-message">{reset_html}</p>
    <ul class="players">{players_html}</ul>
    """


class Handler(BaseHTTPRequestHandler):
    server_version = "SpeakNoBlocksAdmin/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_file(Path("static/index.html"), "text/html; charset=utf-8")
        elif parsed.path == "/static/htmx.min.js":
            self.send_file(Path("static/htmx.min.js"), "text/javascript; charset=utf-8")
        elif parsed.path == "/static/alpine.min.js":
            self.send_file(Path("static/alpine.min.js"), "text/javascript; charset=utf-8")
        elif parsed.path == "/static/style.css":
            self.send_file(Path("static/style.css"), "text/css; charset=utf-8")
        elif parsed.path == "/fragments/status":
            self.send_html(HTTPStatus.OK, status_fragment())
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/actions/op":
                player = validate_player(form_value(request_body(self), "player"))
                output = rcon.command(f"op {player}")
                self.send_html(HTTPStatus.OK, action_message(f"{player} est maintenant admin.", output))
            elif parsed.path == "/actions/give":
                body = request_body(self)
                player = validate_player(form_value(body, "player"))
                item = validate_item(form_value(body, "item"))
                amount = validate_amount(form_value(body, "amount"))
                output = rcon.command(f"give {player} {item} {amount}")
                self.send_html(HTTPStatus.OK, action_message(f"{amount} × {item} donné à {player}.", output))
            elif parsed.path == "/actions/reset":
                request_body(self)
                # Every reset rolls a fresh random seed, even while the
                # server is offline: no need to read the current world first.
                seed = resolve_seed("random")
                self.reset_world(seed)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except ValueError as error:
            self.send_html(HTTPStatus.BAD_REQUEST, action_message(str(error), ""))
        except (OSError, RconError) as error:
            self.send_html(HTTPStatus.BAD_GATEWAY, action_message(f"Minecraft ne répond pas : {error}", ""))

    def reset_world(self, seed: str) -> None:
        global resetting, last_reset_message
        with reset_lock:
            if resetting:
                self.send_html(HTTPStatus.CONFLICT, action_message("Un reset est déjà en cours.", ""))
                return
            write_reset_request(seed)
            resetting = True
            last_reset_message = f"Reset demandé avec la seed {seed}. Sauvegarde et redémarrage en cours..."
            try:
                rcon.command("save-all flush")
                rcon.command("stop")
            except (OSError, RconError):
                # The stop command commonly closes RCON immediately; Docker's
                # restart policy then starts the wrapper that consumes the file.
                pass
            threading.Thread(target=reset_worker, args=(seed,), daemon=True).start()
        self.send_html(HTTPStatus.ACCEPTED, action_message(
            f"Reset lancé avec la seed {seed}. L'ancien monde est sauvegardé automatiquement.", ""))

    def send_file(self, path: Path, content_type: str) -> None:
        try:
            content = path.read_bytes()
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status: HTTPStatus, payload: dict[str, Any], extra_headers: dict[str, str] | None = None) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def send_html(self, http_status: HTTPStatus, content: str) -> None:
        # HTMX only needs a small HTML fragment for actions and status polling.
        encoded = content.encode("utf-8")
        self.send_response(http_status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        # Never log tokens, cookies, or voice data.
        print(f"admin: {self.address_string()} {format % args}", flush=True)


def action_message(message: str, detail: str) -> str:
    extra = f"<small>{html_escape(detail)}</small>" if detail else ""
    return f'<div class="action-message ok"><strong>{html_escape(message)}</strong>{extra}</div>'


def main() -> None:
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Admin panel listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
