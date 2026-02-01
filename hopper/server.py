"""Unix socket JSONL server for hopper."""

import json
import logging
import queue
import socket
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class Server:
    """Broadcast message server over Unix domain socket.

    Uses a single writer thread to serialize all broadcasts, preventing
    race conditions when multiple client handler threads send concurrently.
    """

    def __init__(self, socket_path: Path):
        self.socket_path = socket_path
        self.clients: list[socket.socket] = []
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.server_socket: socket.socket | None = None
        self.broadcast_queue: queue.Queue = queue.Queue(maxsize=10000)
        self.writer_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the server (blocking)."""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove stale socket file
        if self.socket_path.exists():
            self.socket_path.unlink()

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.bind(str(self.socket_path))
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)

        # Start writer thread
        self.writer_thread = threading.Thread(
            target=self._writer_loop, name="server-writer", daemon=True
        )
        self.writer_thread.start()

        logger.info(f"Server listening on {self.socket_path}")

        try:
            while not self.stop_event.is_set():
                try:
                    conn, _ = self.server_socket.accept()
                    threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if not self.stop_event.is_set():
                        logger.error(f"Accept error: {e}")
        finally:
            self.server_socket.close()
            if self.socket_path.exists():
                self.socket_path.unlink()

    def _handle_client(self, conn: socket.socket) -> None:
        """Handle a client connection."""
        with self.lock:
            self.clients.append(conn)

        logger.debug(f"Client connected ({len(self.clients)} total)")

        try:
            conn.settimeout(2.0)
            buffer = ""
            while not self.stop_event.is_set():
                try:
                    data = conn.recv(4096)
                    if not data:
                        break

                    buffer += data.decode("utf-8")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if line.strip():
                            try:
                                message = json.loads(line)
                                self._handle_message(message, conn)
                            except json.JSONDecodeError:
                                pass
                except socket.timeout:
                    continue
        except Exception as e:
            logger.debug(f"Client error: {e}")
        finally:
            with self.lock:
                if conn in self.clients:
                    self.clients.remove(conn)
            try:
                conn.close()
            except Exception:
                pass
            logger.debug(f"Client disconnected ({len(self.clients)} remaining)")

    def _handle_message(self, message: dict, conn: socket.socket) -> None:
        """Handle an incoming message, responding directly if needed."""
        msg_type = message.get("type")

        if msg_type == "ping":
            # Respond directly to the sender
            response = json.dumps({"type": "pong", "ts": int(time.time() * 1000)}) + "\n"
            try:
                conn.sendall(response.encode("utf-8"))
            except Exception as e:
                logger.debug(f"Failed to send pong: {e}")
        else:
            # Broadcast other messages
            self.broadcast(message)

    def _writer_loop(self) -> None:
        """Dedicated writer thread that serializes all broadcasts."""
        while not self.stop_event.is_set():
            try:
                message = self.broadcast_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            self._send_to_clients(message)

    def _send_to_clients(self, message: dict) -> None:
        """Send a message to all connected clients."""
        if "ts" not in message:
            message["ts"] = int(time.time() * 1000)

        data = (json.dumps(message) + "\n").encode("utf-8")

        with self.lock:
            clients_to_send = list(self.clients)

        dead_clients = []
        for client in clients_to_send:
            try:
                client.settimeout(2.0)
                client.sendall(data)
            except Exception as e:
                logger.debug(f"Failed to send to client: {e}")
                dead_clients.append(client)

        if dead_clients:
            with self.lock:
                for client in dead_clients:
                    if client in self.clients:
                        self.clients.remove(client)
                    try:
                        client.close()
                    except Exception:
                        pass

    def broadcast(self, message: dict) -> bool:
        """Queue message for broadcast to all connected clients."""
        if "type" not in message:
            logger.warning("Skipping message without type field")
            return False

        try:
            self.broadcast_queue.put_nowait(message)
            return True
        except queue.Full:
            logger.warning(f"Broadcast queue full, dropping: {message.get('type')}")
            return False

    def stop(self) -> None:
        """Stop the server."""
        self.stop_event.set()

        if self.writer_thread and self.writer_thread.is_alive():
            self.writer_thread.join(timeout=1.0)


def start_server(socket_path: Path) -> None:
    """Start the server, handling KeyboardInterrupt."""
    server = Server(socket_path)
    try:
        server.start()
    except KeyboardInterrupt:
        logger.info("Shutting down server")
        server.stop()
