from __future__ import annotations

import asyncio
import json
import os
import shlex
import signal
import sys
from asyncio.subprocess import Process
from base64 import b64encode
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from .adapters import LoadedEvaluator
from .models import (
    AdapterConfig,
    AdapterLoadError,
    AdapterRuntimeError,
    FrameSample,
    TargetContext,
)

PROCESS_ADAPTER_PROTOCOL_VERSION = 1
MAX_PROTOCOL_MESSAGE_BYTES = 256 * 1024 * 1024
STDERR_TAIL_BYTES = 64 * 1024
GRACEFUL_EXIT_TIMEOUT_S = 5.0
TERMINATE_TIMEOUT_S = 2.0
EXIT_STATUS_TIMEOUT_S = 0.25
LEADER_EXIT_POLL_INTERVAL_S = 0.02


async def load_process_evaluator(
    adapter_command: str, config: AdapterConfig
) -> LoadedEvaluator:
    argv = _parse_adapter_command(adapter_command)
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=MAX_PROTOCOL_MESSAGE_BYTES,
            start_new_session=os.name == "posix",
        )
    except OSError as error:
        raise AdapterLoadError(
            f"could not start adapter command {_command_label(argv)}: {error}"
        ) from error

    transport = _ProcessAdapter(process, argv)
    try:
        capabilities = await transport.initialize(config)
    except asyncio.CancelledError:
        await asyncio.shield(transport.abort())
        raise
    except Exception as error:
        await transport.abort()
        if isinstance(error, AdapterLoadError):
            raise
        raise AdapterLoadError(
            f"adapter command {_command_label(argv)} failed to initialize: {error}"
        ) from error

    return LoadedEvaluator(
        evaluate=transport.evaluate if capabilities.evaluate else None,
        evaluate_many=(transport.evaluate_many if capabilities.evaluate_many else None),
        close=transport.close,
    )


@dataclass(frozen=True)
class _Capabilities:
    evaluate: bool
    evaluate_many: bool


@dataclass(frozen=True)
class _PendingRequest:
    method: str
    future: asyncio.Future[Any]


class _ProcessAdapter:
    def __init__(self, process: Process, argv: list[str]) -> None:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise RuntimeError("internal error: adapter process pipes are unavailable")
        self._process = process
        self._stdin = process.stdin
        self._stdout = process.stdout
        self._stderr = process.stderr
        self._command = _command_label(argv)
        self._next_request_id = 1
        self._pending: dict[int, _PendingRequest] = {}
        self._write_lock = asyncio.Lock()
        self._failure: AdapterRuntimeError | None = None
        self._closing = False
        self._closed = False
        self._stderr_tail = bytearray()
        self._process_wait_task = asyncio.create_task(self._process.wait())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        self._reader_task = asyncio.create_task(self._read_responses())
        self._exit_monitor_task = asyncio.create_task(self._monitor_process_exit())

    async def initialize(self, config: AdapterConfig) -> _Capabilities:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROCESS_ADAPTER_PROTOCOL_VERSION,
                "config": {
                    "evalDir": str(config.eval_dir.expanduser().resolve()),
                    "config": dict(config.config),
                    "artifactsDir": (
                        str(config.artifacts_dir.expanduser().resolve())
                        if config.artifacts_dir is not None
                        else None
                    ),
                    "verbose": config.verbose,
                },
            },
        )
        return _parse_capabilities(result)

    async def evaluate(self, sample: FrameSample, target: TargetContext) -> Any:
        sample_payload = await asyncio.to_thread(_sample_payload, sample)
        return await self._request(
            "evaluate",
            {"sample": sample_payload, "target": _target_payload(target)},
        )

    async def evaluate_many(
        self, samples: list[FrameSample], target: TargetContext
    ) -> Any:
        sample_payloads = await asyncio.to_thread(
            lambda: [_sample_payload(sample) for sample in samples]
        )
        return await self._request(
            "evaluateMany",
            {"samples": sample_payloads, "target": _target_payload(target)},
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closing = True
        if self._failure is not None:
            failure = self._failure
            await self._run_forced_shutdown()
            self._closed = True
            raise failure

        close_error: BaseException | None = None
        forced = False
        try:
            async with asyncio.timeout(GRACEFUL_EXIT_TIMEOUT_S):
                try:
                    await self._request("close", {})
                except Exception as error:
                    close_error = error
                await self._close_stdin()
                await self._wait_for_transport_completion()
        except TimeoutError:
            forced = True
        except BaseException:
            await self._run_forced_shutdown()
            self._closed = True
            raise

        if forced:
            termination_scope = (
                "process tree" if os.name == "posix" else "adapter process"
            )
            shutdown_error = AdapterRuntimeError(
                f"adapter command {self._command} did not complete close within "
                f"{GRACEFUL_EXIT_TIMEOUT_S:g}s; the {termination_scope} was terminated"
            )
            self._set_failure(shutdown_error)
            await self._run_forced_shutdown()
            self._closed = True
            raise shutdown_error

        self._closed = True
        if self._failure is not None:
            if close_error is not None and close_error is not self._failure:
                self._failure.add_note(f"adapter close also failed: {close_error}")
            raise self._failure

        if close_error is not None:
            raise close_error
        if self._process.returncode != 0:
            raise AdapterRuntimeError(self._exit_message("exited after close"))

    async def abort(self) -> None:
        if self._closed:
            return
        self._closing = True
        await self._run_forced_shutdown()
        self._closed = True

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        if self._closed or self._closing and method != "close":
            raise AdapterRuntimeError(f"adapter command is closed: {self._command}")
        if self._failure is not None:
            raise self._failure

        request_id = self._next_request_id
        self._next_request_id += 1
        message = _encode_message(
            {"id": request_id, "method": method, "params": params},
            method=method,
        )
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = _PendingRequest(method=method, future=future)
        write_task = asyncio.create_task(self._write_message(message))
        write_completion_task = asyncio.create_task(
            _wait_for_write_or_response(write_task, future)
        )
        try:
            await asyncio.shield(write_completion_task)
        except asyncio.CancelledError:
            if method == "close":
                write_completion_task.cancel()
                write_task.cancel()
                await asyncio.gather(
                    write_completion_task, write_task, return_exceptions=True
                )
                future.cancel()
                raise
            if not write_task.done():
                self._closing = True
                write_completion_task.cancel()
                write_task.cancel()
                future.cancel()
                self._pending.pop(request_id, None)
                await asyncio.gather(
                    write_completion_task, write_task, return_exceptions=True
                )
                await self.abort()
                raise
            await _drain_task(write_completion_task)
            if not write_task.cancelled() and write_task.exception() is None:
                await self._cancel_request(request_id)
            future.cancel()
            raise
        except Exception:
            self._pending.pop(request_id, None)
            future.cancel()
            raise

        try:
            return await future
        except asyncio.CancelledError:
            future.cancel()
            if method != "close":
                await self._cancel_request(request_id)
            raise

    async def _cancel_request(self, request_id: int) -> None:
        try:
            await asyncio.shield(
                self._write_message(
                    _encode_message(
                        {"method": "cancel", "params": {"id": request_id}},
                        method="cancel",
                    )
                )
            )
        except BaseException:
            return

    async def _write_message(self, message: bytes) -> None:
        if self._failure is not None:
            raise self._failure
        try:
            async with self._write_lock:
                self._stdin.write(message)
                await self._stdin.drain()
        except (BrokenPipeError, ConnectionError, OSError) as error:
            failure = AdapterRuntimeError(
                self._exit_message(f"could not write to adapter process: {error}")
            )
            self._set_failure(failure)
            raise failure from error

    async def _read_responses(self) -> None:
        try:
            while True:
                try:
                    line = await self._stdout.readline()
                except ValueError:
                    self._set_failure(
                        self._protocol_error(
                            "stdout message exceeds the 256 MiB protocol limit"
                        )
                    )
                    return
                if not line:
                    if not self._closing or self._pending:
                        await self._collect_exit_details()
                        self._set_failure(
                            AdapterRuntimeError(
                                self._exit_message("closed stdout unexpectedly")
                            )
                        )
                    return
                try:
                    response = json.loads(
                        line,
                        parse_constant=lambda value: _reject_json_constant(value),
                    )
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                    preview = line[:200].decode("utf-8", errors="replace").rstrip()
                    self._set_failure(
                        self._protocol_error(
                            f"invalid JSON on stdout: {error}; line: {preview!r}"
                        )
                    )
                    return
                error = self._handle_response(response)
                if error is not None:
                    self._set_failure(error)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._set_failure(
                self._protocol_error(f"failed while reading stdout: {error}")
            )

    def _handle_response(self, response: Any) -> AdapterRuntimeError | None:
        if not isinstance(response, dict):
            return self._protocol_error("stdout response must be a JSON object")
        request_id = response.get("id")
        if not isinstance(request_id, int) or isinstance(request_id, bool):
            return self._protocol_error("stdout response must contain an integer id")
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return self._protocol_error(
                f"stdout response has unknown request id {request_id}"
            )
        has_result = "result" in response
        has_error = "error" in response
        if has_result == has_error:
            error = self._protocol_error(
                "stdout response must contain exactly one of result or error"
            )
            if not pending.future.done():
                pending.future.set_exception(error)
            return error
        if has_error:
            error_payload = response["error"]
            if not isinstance(error_payload, dict) or not isinstance(
                error_payload.get("message"), str
            ):
                error = self._protocol_error(
                    "stdout error response must contain a string error.message"
                )
                if not pending.future.done():
                    pending.future.set_exception(error)
                return error
            error = AdapterRuntimeError(
                f"adapter command {pending.method} failed: {error_payload['message']}"
            )
            if not pending.future.done():
                pending.future.set_exception(error)
            return None
        if not pending.future.done():
            pending.future.set_result(response["result"])
        return None

    async def _read_stderr(self) -> None:
        while True:
            chunk = await self._stderr.read(64 * 1024)
            if not chunk:
                return
            self._stderr_tail.extend(chunk)
            if len(self._stderr_tail) > STDERR_TAIL_BYTES:
                del self._stderr_tail[:-STDERR_TAIL_BYTES]
            _forward_stderr(chunk)

    async def _monitor_process_exit(self) -> None:
        while self._process.returncode is None:
            await asyncio.sleep(LEADER_EXIT_POLL_INTERVAL_S)
        await self._wait_for_stderr_tail()
        await self._allow_buffered_close_response()
        if not self._closing or self._pending:
            self._set_failure(
                AdapterRuntimeError(self._exit_message("exited unexpectedly"))
            )

    async def _allow_buffered_close_response(self) -> None:
        if not self._closing or not self._pending:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + EXIT_STATUS_TIMEOUT_S
        while self._pending and loop.time() < deadline:
            await asyncio.sleep(LEADER_EXIT_POLL_INTERVAL_S)

    async def _collect_exit_details(self) -> None:
        try:
            await asyncio.wait_for(
                asyncio.shield(self._process_wait_task),
                timeout=EXIT_STATUS_TIMEOUT_S,
            )
        except TimeoutError:
            return
        await self._wait_for_stderr_tail()

    async def _wait_for_stderr_tail(self) -> None:
        try:
            await asyncio.wait_for(
                asyncio.shield(self._stderr_task),
                timeout=EXIT_STATUS_TIMEOUT_S,
            )
        except TimeoutError:
            pass

    def _set_failure(self, error: AdapterRuntimeError) -> None:
        if self._failure is not None:
            return
        self._failure = error
        pending = list(self._pending.values())
        self._pending.clear()
        for request in pending:
            if not request.future.done():
                request.future.set_exception(error)

    def _protocol_error(self, detail: str) -> AdapterRuntimeError:
        return AdapterRuntimeError(
            f"adapter command protocol error: {detail}. Stdout is reserved for "
            "NDJSON protocol messages; write adapter logs to stderr"
        )

    def _exit_message(self, action: str) -> str:
        returncode = self._process.returncode
        status = (
            f"exit code {returncode}" if returncode is not None else "no exit status"
        )
        message = f"adapter command {self._command} {action} ({status})"
        if tail := self._stderr_text():
            message += f"; stderr tail: {tail}"
        return message

    def _stderr_text(self) -> str:
        return bytes(self._stderr_tail).decode("utf-8", errors="replace").strip()

    async def _close_stdin(self) -> None:
        if self._stdin.is_closing():
            return
        self._stdin.close()
        try:
            await self._stdin.wait_closed()
        except (BrokenPipeError, ConnectionError, OSError):
            pass

    async def _wait_for_transport_completion(self) -> None:
        await asyncio.shield(self._process_wait_task)
        tasks = {
            self._reader_task,
            self._stderr_task,
            self._exit_monitor_task,
        }
        await asyncio.wait(tasks, return_when=asyncio.ALL_COMPLETED)
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_forced_shutdown(self) -> None:
        cleanup_task = asyncio.create_task(self._force_shutdown())
        await _drain_task(cleanup_task)

    async def _force_shutdown(self) -> None:
        if not self._stdin.is_closing():
            self._stdin.close()
        _signal_process(self._process, self._process.terminate, signal.SIGTERM)
        if await self._wait_for_transport_tasks(TERMINATE_TIMEOUT_S):
            return
        kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
        _signal_process(self._process, self._process.kill, kill_signal)
        await self._wait_for_transport_tasks(TERMINATE_TIMEOUT_S)
        await self._cancel_transport_tasks()

    async def _wait_for_transport_tasks(self, timeout_s: float) -> bool:
        tasks = {
            self._process_wait_task,
            self._reader_task,
            self._stderr_task,
            self._exit_monitor_task,
        }
        _, pending = await asyncio.wait(tasks, timeout=timeout_s)
        if not pending:
            await asyncio.gather(*tasks, return_exceptions=True)
            return True
        return False

    async def _cancel_transport_tasks(self) -> None:
        tasks = {
            self._process_wait_task,
            self._reader_task,
            self._stderr_task,
            self._exit_monitor_task,
        }
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _parse_adapter_command(adapter_command: str) -> list[str]:
    if not adapter_command.strip():
        raise AdapterLoadError("adapter command must not be empty")
    try:
        argv = (
            _split_windows_command(adapter_command)
            if os.name == "nt"
            else shlex.split(adapter_command, posix=True)
        )
    except (OSError, ValueError) as error:
        raise AdapterLoadError(f"invalid adapter command: {error}") from error
    if not argv:
        raise AdapterLoadError("adapter command must not be empty")
    return argv


def _split_windows_command(adapter_command: str) -> list[str]:
    import ctypes
    from ctypes import wintypes

    windows_ctypes: Any = ctypes
    win_dll = windows_ctypes.WinDLL
    shell32 = win_dll("shell32", use_last_error=True)
    command_line_to_argv = shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_int),
    ]
    command_line_to_argv.restype = ctypes.POINTER(wintypes.LPWSTR)

    argument_count = ctypes.c_int()
    arguments = command_line_to_argv(
        adapter_command.lstrip(), ctypes.byref(argument_count)
    )
    if not arguments:
        get_last_error = windows_ctypes.get_last_error
        raise OSError(get_last_error(), "could not parse Windows command line")

    try:
        return [arguments[index] for index in range(argument_count.value)]
    finally:
        kernel32 = win_dll("kernel32", use_last_error=True)
        local_free = kernel32.LocalFree
        local_free.argtypes = [wintypes.HLOCAL]
        local_free.restype = wintypes.HLOCAL
        local_free(arguments)


def _command_label(argv: list[str]) -> str:
    return repr(shlex.join(argv))


def _parse_capabilities(result: Any) -> _Capabilities:
    if not isinstance(result, dict):
        raise AdapterLoadError("initialize result must be a JSON object")
    if result.get("protocolVersion") != PROCESS_ADAPTER_PROTOCOL_VERSION:
        raise AdapterLoadError("initialize result must declare protocolVersion 1")
    raw = result.get("capabilities")
    if not isinstance(raw, dict):
        raise AdapterLoadError("initialize result must contain capabilities")
    evaluate = raw.get("evaluate") is True
    evaluate_many = raw.get("evaluateMany") is True
    if not evaluate and not evaluate_many:
        raise AdapterLoadError("adapter command must support evaluate or evaluateMany")
    return _Capabilities(evaluate=evaluate, evaluate_many=evaluate_many)


def _sample_payload(sample: FrameSample) -> dict[str, Any]:
    output = BytesIO()
    sample.image.save(output, format="PNG")
    width, height = sample.image.size
    return {
        "image": {
            "mimeType": "image/png",
            "dataBase64": b64encode(output.getvalue()).decode("ascii"),
            "width": width,
            "height": height,
        },
        "timestampS": sample.timestamp_s,
        "frameIndex": sample.frame_index,
        "sampleIndex": sample.sample_index,
        "videoPath": sample.video_path,
        "caseName": sample.case_name,
    }


def _target_payload(target: TargetContext) -> dict[str, Any]:
    return {
        "id": target.id,
        "index": target.index,
        "label": target.label,
        "config": dict(target.config),
    }


def _encode_message(message: dict[str, Any], *, method: str) -> bytes:
    try:
        encoded = json.dumps(
            message,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise AdapterRuntimeError(
            f"adapter command {method} request is not JSON serializable: {error}"
        ) from error
    if len(encoded) > MAX_PROTOCOL_MESSAGE_BYTES:
        raise AdapterRuntimeError(
            f"adapter command {method} request exceeds the 256 MiB protocol limit"
        )
    return encoded + b"\n"


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"invalid JSON constant {value}")


async def _drain_task(task: asyncio.Task[Any]) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except BaseException:
            return


async def _wait_for_write_or_response(
    write_task: asyncio.Task[None], response_future: asyncio.Future[Any]
) -> None:
    done, _ = await asyncio.wait(
        {write_task, response_future},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if write_task in done:
        await write_task
        return

    write_task.cancel()
    await asyncio.gather(write_task, return_exceptions=True)
    await response_future


def _signal_process(process: Process, fallback: Any, process_signal: int) -> None:
    if os.name == "posix" and process.pid is not None:
        try:
            os.killpg(process.pid, process_signal)
            return
        except ProcessLookupError:
            return
    try:
        fallback()
    except ProcessLookupError:
        pass


def _forward_stderr(chunk: bytes) -> None:
    buffer = getattr(sys.stderr, "buffer", None)
    if buffer is not None:
        buffer.write(chunk)
        buffer.flush()
        return
    sys.stderr.write(chunk.decode("utf-8", errors="replace"))
    sys.stderr.flush()
