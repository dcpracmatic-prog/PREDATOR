"""Optional, non-authoritative determinism evidence for ZTGE.

This module is diagnostic only. It never decides whether a graph or claim is
valid, and it is not a security boundary.
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
import statistics
import sys
import time
import types
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Mapping

try:
    import resource
except ImportError:
    resource = None


@dataclass(frozen=True)
class Measurement:
    wall_ns: int
    thread_cpu_ns: int | None
    process_cpu_ns: int | None
    thread_run_delay_ns: int | None
    cpu_scope: str
    platform: str
    python: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkCount:
    line_events: int
    calls: int
    value: Any

    def to_dict(self, include_value: bool = False) -> dict[str, Any]:
        result = {"line_events": self.line_events, "calls": self.calls}
        if include_value:
            result["value"] = self.value
        return result


@dataclass(frozen=True)
class BenchmarkResult:
    repetitions: int
    warmups: int
    samples_ns: tuple[int, ...]
    minimum_ns: int
    median_ns: float
    p95_ns: int
    maximum_ns: int
    last_value: Any

    def to_dict(self, include_value: bool = False) -> dict[str, Any]:
        result = {
            "repetitions": self.repetitions,
            "warmups": self.warmups,
            "samples_ns": list(self.samples_ns),
            "minimum_ns": self.minimum_ns,
            "median_ns": self.median_ns,
            "p95_ns": self.p95_ns,
            "maximum_ns": self.maximum_ns,
        }
        if include_value:
            result["last_value"] = self.last_value
        return result


def _thread_cpu_ns() -> int | None:
    clock = getattr(time, "thread_time_ns", None)
    if clock is None:
        return None
    try:
        return int(clock())
    except (OSError, RuntimeError):
        return None


def _resource_cpu_ns() -> tuple[int | None, str]:
    """Return process-wide CPU time; thread time has its own clock above."""
    if resource is None:
        return None, "unavailable"
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return int((usage.ru_utime + usage.ru_stime) * 1_000_000_000), "process"
    except (OSError, ValueError, AttributeError):
        return None, "unavailable"


def _run_delay_ns() -> int | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open("/proc/thread-self/schedstat", encoding="ascii") as stream:
            fields = stream.read().split()
        return int(fields[1]) if len(fields) >= 2 else None
    except (OSError, ValueError, IndexError):
        return None


class Meter:
    """Measure one interval using portable clocks where available."""

    def __init__(self) -> None:
        self._started = False

    def start(self) -> "Meter":
        self._wall = time.perf_counter_ns()
        self._thread = _thread_cpu_ns()
        self._process, self._scope = _resource_cpu_ns()
        self._delay = _run_delay_ns()
        self._started = True
        return self

    def stop(self) -> Measurement:
        if not self._started:
            raise RuntimeError("Meter.start() must be called before stop()")
        wall_end = time.perf_counter_ns()
        thread_end = _thread_cpu_ns()
        process_end, scope_end = _resource_cpu_ns()
        delay_end = _run_delay_ns()
        return Measurement(
            wall_ns=max(0, wall_end - self._wall),
            thread_cpu_ns=max(0, thread_end - self._thread) if thread_end is not None and self._thread is not None else None,
            process_cpu_ns=max(0, process_end - self._process) if process_end is not None and self._process is not None else None,
            thread_run_delay_ns=max(0, delay_end - self._delay) if delay_end is not None and self._delay is not None else None,
            cpu_scope="thread_time_ns" if self._thread is not None and thread_end is not None else scope_end,
            platform=platform.platform(),
            python=platform.python_version(),
        )


def best_of_k(function: Callable[..., Any], *args: Any, k: int = 7, warmups: int = 1, **kwargs: Any) -> BenchmarkResult:
    """Report raw samples and min/median/p95/max; minimum is not typical latency."""
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 10000:
        raise ValueError("k must be an integer in [1, 10000]")
    if isinstance(warmups, bool) or not isinstance(warmups, int) or not 0 <= warmups <= 10000:
        raise ValueError("warmups must be an integer in [0, 10000]")
    for _ in range(warmups):
        function(*args, **kwargs)
    samples = []
    last_value = None
    for _ in range(k):
        meter = Meter().start()
        last_value = function(*args, **kwargs)
        samples.append(meter.stop().wall_ns)
    ordered = sorted(samples)
    p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    return BenchmarkResult(k, warmups, tuple(samples), ordered[0], float(statistics.median(ordered)), p95, ordered[-1], last_value)


def _describe(value: Any, stack: set[int], opaque: list[str]) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return {"float_hex": value.hex()} if math.isfinite(value) else {"nonfinite_float": repr(value)}
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, type):
        return {"type": value.__module__ + "." + value.__qualname__}
    if isinstance(value, types.CodeType):
        return {
            "bytecode": value.co_code.hex(), "names": list(value.co_names),
            "varnames": list(value.co_varnames), "argcount": value.co_argcount,
            "posonlyargcount": value.co_posonlyargcount, "kwonlyargcount": value.co_kwonlyargcount,
            "flags": value.co_flags, "constants": [_describe(x, stack, opaque) for x in value.co_consts],
        }
    ident = id(value)
    if ident in stack:
        return {"cycle_type": type(value).__module__ + "." + type(value).__qualname__}
    if isinstance(value, (tuple, list, set, frozenset, dict)):
        stack.add(ident)
        try:
            if isinstance(value, dict):
                pairs = [(_describe(k, stack, opaque), _describe(v, stack, opaque)) for k, v in value.items()]
                pairs.sort(key=lambda p: json.dumps(p[0], sort_keys=True, separators=(",", ":")))
                return {"dict": pairs}
            items = [_describe(x, stack, opaque) for x in value]
            if isinstance(value, (set, frozenset)):
                items.sort(key=lambda x: json.dumps(x, sort_keys=True, separators=(",", ":")))
            return {"tuple" if isinstance(value, tuple) else "set" if isinstance(value, (set, frozenset)) else "list": items}
        finally:
            stack.remove(ident)
    if isinstance(value, types.ModuleType):
        return {"module": value.__name__, "file": getattr(value, "__file__", None)}
    if isinstance(value, types.FunctionType):
        return {
            "function": value.__module__ + "." + value.__qualname__,
            "code": _describe(value.__code__, stack, opaque),
            "defaults": _describe(value.__defaults__, stack, opaque),
            "kwdefaults": _describe(value.__kwdefaults__, stack, opaque),
        }
    if isinstance(value, (types.BuiltinFunctionType, types.BuiltinMethodType)):
        return {"builtin": getattr(value, "__module__", None), "name": getattr(value, "__qualname__", value.__name__)}
    opaque.append(type(value).__module__ + "." + type(value).__qualname__)
    return {"opaque_type": type(value).__module__ + "." + type(value).__qualname__}


def code_identity(functions: Iterable[Callable[..., Any]]) -> dict[str, Any]:
    """Hash code, defaults, closure cells and referenced globals; opaque state is disclosed."""
    records = []
    opaque: list[str] = []
    for function in functions:
        if not isinstance(function, types.FunctionType):
            raise TypeError("code_identity accepts Python functions only")
        code = function.__code__
        globals_used = {name: _describe(function.__globals__[name], set(), opaque)
                        for name in sorted(set(code.co_names)) if name in function.__globals__}
        closure = {}
        if function.__closure__:
            for name, cell in zip(code.co_freevars, function.__closure__):
                try:
                    closure[name] = _describe(cell.cell_contents, set(), opaque)
                except ValueError:
                    closure[name] = {"empty_cell": True}
        records.append({
            "name": function.__module__ + "." + function.__qualname__,
            "code": _describe(code, set(), opaque),
            "defaults": _describe(function.__defaults__, set(), opaque),
            "kwdefaults": _describe(function.__kwdefaults__, set(), opaque),
            "annotations": _describe(function.__annotations__, set(), opaque),
            "globals": globals_used, "closure": closure,
        })
    records.sort(key=lambda record: record["name"])
    payload = {"schema": "ztge-determinism-witness-v1", "implementation": sys.implementation.name,
               "python": platform.python_version(), "functions": records}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "schema": payload["schema"], "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "complete": not opaque, "opaque_bindings": sorted(set(opaque)),
        "python_implementation": payload["implementation"], "python_version": payload["python"],
        "function_count": len(records),
    }


def count_work(function: Callable[..., Any], *args: Any, target_functions: Iterable[Callable[..., Any]] | None = None, **kwargs: Any) -> WorkCount:
    """Count Python line/call events in selected functions only, restoring tracing on exceptions."""
    if sys.gettrace() is not None:
        raise RuntimeError("count_work refuses to replace an active trace hook")
    targets = tuple(target_functions) if target_functions is not None else (function,)
    codes = set()
    for target in targets:
        if not isinstance(target, types.FunctionType):
            raise TypeError("target_functions must contain Python functions")
        codes.add(target.__code__)
    lines = 0
    calls = 0

    def trace(frame: Any, event: str, arg: Any) -> Any:
        nonlocal lines, calls
        if frame.f_code not in codes:
            return None
        if event == "line":
            lines += 1
        elif event == "call":
            calls += 1
        return trace

    sys.settrace(trace)
    try:
        value = function(*args, **kwargs)
    finally:
        sys.settrace(None)
    return WorkCount(lines, calls, value)


def expected_work(hops: int, *, intercept: float, slope: float) -> float:
    """Evaluate an explicit affine model; this does not prove the model is valid."""
    if isinstance(hops, bool) or not isinstance(hops, int) or hops < 0:
        raise ValueError("hops must be a non-negative integer")
    for name, value in (("intercept", intercept), ("slope", slope)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(name + " must be a finite non-negative number")
        try:
            finite = math.isfinite(value)
        except (OverflowError, TypeError):
            finite = False
        if not finite:
            raise ValueError(name + " must be a finite non-negative number")
    result = intercept + slope * hops
    if not math.isfinite(float(result)):
        raise ValueError("computed work must be finite")
    return float(result)


def evidence_manifest(*, identity: Mapping[str, Any], measurement: Measurement | None = None, work: WorkCount | None = None) -> dict[str, Any]:
    """Return a JSON-safe evidence record that explicitly cannot authorize a verdict."""
    result: dict[str, Any] = {
        "schema": "ztge-evidence-manifest-v1", "authoritative": False,
        "limitations": [
            "In-process measurements are not a security boundary.",
            "Python line counts exclude C/native work and unselected functions.",
            "Timing varies with platform, scheduler, caches and runtime state.",
            "Code identity is partial when opaque bindings are reported.",
        ],
        "identity": dict(identity),
    }
    if measurement is not None:
        result["measurement"] = measurement.to_dict()
    if work is not None:
        result["work"] = work.to_dict()
    json.dumps(result, allow_nan=False, sort_keys=True)
    return result
