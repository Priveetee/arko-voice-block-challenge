#!/usr/bin/env python3
"""Local, queue-backed Whisper service for Speak No Blocks.

The Minecraft mod sends only short 16 kHz mono PCM utterances over the private
Docker network. No audio is logged or written to disk.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import numpy as np
from faster_whisper import WhisperModel


LOG = logging.getLogger("speak-no-blocks-asr")
HOST = os.getenv("ASR_HOST", "0.0.0.0")
PORT = int(os.getenv("ASR_PORT", "8080"))
MODEL_NAME = os.getenv("WHISPER_MODEL", "large-v3-turbo")
MODEL_PATH = os.getenv("WHISPER_MODEL_PATH", "").strip()
MODEL_ROOT = os.getenv("WHISPER_MODEL_ROOT", "/models")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")
MAX_QUEUE = int(os.getenv("ASR_MAX_QUEUE", "16"))
MAX_AUDIO_SECONDS = float(os.getenv("ASR_MAX_AUDIO_SECONDS", "6.5"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("ASR_REQUEST_TIMEOUT_SECONDS", "20"))
INFERENCE_HARD_TIMEOUT_SECONDS = float(os.getenv("ASR_INFERENCE_HARD_TIMEOUT_SECONDS", "60"))
INITIAL_PROMPT = os.getenv("ASR_INITIAL_PROMPT", "").strip()


@dataclass
class Job:
    audio: np.ndarray
    result: queue.Queue[dict[str, Any]]


class InferenceService:
    def __init__(self) -> None:
        model_source = MODEL_PATH or MODEL_NAME
        LOG.info("Loading Whisper model %s on CUDA (%s)", model_source, COMPUTE_TYPE)
        self.model = WhisperModel(
            model_source,
            device="cuda",
            compute_type=COMPUTE_TYPE,
            download_root=MODEL_ROOT,
            num_workers=1,
        )
        self.jobs: queue.Queue[Job | None] = queue.Queue(maxsize=MAX_QUEUE)
        self.stopping = threading.Event()
        self.active_started = 0.0
        self.active_lock = threading.Lock()
        self.worker = threading.Thread(target=self._run, name="whisper-worker", daemon=True)
        self.worker.start()
        self.watchdog = threading.Thread(target=self._watchdog, name="whisper-watchdog", daemon=True)
        self.watchdog.start()
        LOG.info("Whisper model ready; queue capacity=%d", MAX_QUEUE)

    def submit(self, audio: np.ndarray) -> dict[str, Any] | None:
        result: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        try:
            self.jobs.put_nowait(Job(audio=audio, result=result))
        except queue.Full:
            return None

        try:
            return result.get(timeout=REQUEST_TIMEOUT_SECONDS)
        except queue.Empty:
            return {"error": "inference timeout"}

    def close(self) -> None:
        self.stopping.set()
        try:
            self.jobs.put_nowait(None)
        except queue.Full:
            pass
        self.worker.join(timeout=3)

    def health(self) -> dict[str, Any]:
        with self.active_lock:
            active = self.active_started > 0.0
        return {
            "status": "ok" if self.worker.is_alive() and not self.stopping.is_set() else "degraded",
            "queue": self.jobs.qsize(),
            "active": active,
        }

    def _run(self) -> None:
        while not self.stopping.is_set():
            job = self.jobs.get()
            if job is None:
                return
            started = time.perf_counter()
            with self.active_lock:
                self.active_started = time.monotonic()
            try:
                job.result.put(self._transcribe(job.audio))
            except Exception as exc:  # keep the HTTP process alive after one bad request
                LOG.exception("Whisper inference failed")
                job.result.put({"error": str(exc)})
            finally:
                with self.active_lock:
                    self.active_started = 0.0
                LOG.debug("inference completed in %.0f ms", (time.perf_counter() - started) * 1000)

    def _watchdog(self) -> None:
        while not self.stopping.wait(2.0):
            if not self.worker.is_alive():
                LOG.critical("Whisper worker stopped; restarting the ASR process")
                os._exit(1)
            with self.active_lock:
                active_for = time.monotonic() - self.active_started if self.active_started else 0.0
            if active_for > INFERENCE_HARD_TIMEOUT_SECONDS:
                LOG.critical("Whisper inference exceeded %.1f seconds; restarting the ASR process",
                             INFERENCE_HARD_TIMEOUT_SECONDS)
                os._exit(1)

    def _transcribe(self, audio: np.ndarray) -> dict[str, Any]:
        options: dict[str, Any] = {
            "language": "fr",
            "task": "transcribe",
            "beam_size": 5,
            "best_of": 5,
            "temperature": 0.0,
            "condition_on_previous_text": False,
            "vad_filter": True,
            "vad_parameters": {
                "min_silence_duration_ms": 350,
                "speech_pad_ms": 80,
            },
            "word_timestamps": False,
        }
        # An empty prompt avoids Whisper repeating instructions during silence.
        # A deployment may opt into a short, domain-specific prompt explicitly.
        if INITIAL_PROMPT:
            options["initial_prompt"] = INITIAL_PROMPT
        segments, info = self.model.transcribe(audio, **options)

        collected: list[str] = []
        weighted_logprob = 0.0
        weighted_no_speech = 0.0
        total_duration = 0.0
        for segment in segments:
            text = segment.text.strip()
            if text:
                collected.append(text)
            duration = max(0.001, float(segment.end - segment.start))
            weighted_logprob += float(segment.avg_logprob) * duration
            weighted_no_speech += float(segment.no_speech_prob) * duration
            total_duration += duration

        return {
            "text": " ".join(collected),
            "language": getattr(info, "language", "fr"),
            "duration": float(getattr(info, "duration", total_duration)),
            "avg_logprob": weighted_logprob / total_duration if total_duration else -10.0,
            "no_speech_prob": weighted_no_speech / total_duration if total_duration else 1.0,
        }


class Handler(BaseHTTPRequestHandler):
    service: InferenceService

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            health = self.service.health()
            status = HTTPStatus.OK if health["status"] == "ok" else HTTPStatus.SERVICE_UNAVAILABLE
            self._send_json(status, health)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/transcribe":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid content length"})
            return

        max_bytes = int(MAX_AUDIO_SECONDS * 16_000 * 2)
        if content_length <= 0 or content_length > max_bytes or content_length % 2 != 0:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "audio length outside limits"})
            return

        body = self.rfile.read(content_length)
        if len(body) != content_length:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "incomplete audio body"})
            return

        audio = np.frombuffer(body, dtype="<i2").astype(np.float32) / 32768.0
        result = self.service.submit(audio)
        if result is None:
            self._send_json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "inference queue full"})
        elif "error" in result:
            self._send_json(HTTPStatus.SERVICE_UNAVAILABLE, result)
        else:
            self._send_json(HTTPStatus.OK, result)

    def log_message(self, format: str, *args: object) -> None:
        # Do not log request headers or audio metadata containing player identity.
        LOG.debug("http: " + format, *args)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except BrokenPipeError:
            # A client timing out must not affect the inference worker or the
            # HTTP accept loop.
            pass


class LocalHttpServer(ThreadingHTTPServer):
    request_queue_size = 64
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    service = InferenceService()
    Handler.service = service
    httpd = LocalHttpServer((HOST, PORT), Handler)

    def stop(_signal: int, _frame: object) -> None:
        LOG.info("Stopping ASR service")
        service.close()
        # shutdown() must run from a thread other than serve_forever(); signal
        # handlers execute on that same main thread and would otherwise hang.
        threading.Thread(target=httpd.shutdown, name="http-shutdown", daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info("ASR service listening on %s:%d", HOST, PORT)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
