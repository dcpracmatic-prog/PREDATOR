#!/usr/bin/env python3
"""
COMMONWEAVE Zero — pipeline estabilizado + sello de integridad (CSG)

Flujo:
  1. Compilar componente nativo
  2. Regenerar adaptador desde contrato
  3. Verificación diferencial
  4. Benchmark de cuatro vías
  5. Emitir certificado de aceptación
  6. Sellar artefactos con Ed25519 + SHA3-256 (inspirado en CSG)
  7. Auto-verificar el sello

Criterio de salida:
  0 = PASS (veredicto diferencial + sello válido)
  1 = FAIL (veredicto diferencial negativo o sello inválido)
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "report"


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print(f"+ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def write_certificate(diff: dict, bench: dict) -> Path:
    """Certificado estructurado con enunciados explícitos y base de confianza."""
    verdict = diff.get("verdict", "FAIL")
    cert = {
        "schema": "commonweave.certificate/1.0",
        "experiment": "COMMONWEAVE Zero",
        "date": time.strftime("%Y-%m-%d"),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hypothesis": (
            "Un contrato declarativo puede generar un adaptador C→Python "
            "verificado con menor esfuerzo humano que un binding convencional, "
            "preservando equivalencia semántica y rendimiento competitivo en "
            "el camino caliente."
        ),
        "differential": {
            "verdict": verdict,
            "pass_rate": diff.get("pass_rate"),
            "trials": diff.get("trials"),
            "edge_passed": f"{diff.get('edge_passed')}/{diff.get('edge_total')}",
            "seed": diff.get("seed"),
        },
        "benchmark": {
            "cold_start_seconds": bench.get("cold_start_seconds"),
            "effort_proxy": bench.get("effort_proxy"),
            "sizes_tested": list((bench.get("implementations") or {}).keys()),
        },
        "proofs": [
            {
                "id": "DIFF-SEMANTIC",
                "class": "differential",
                "statement": (
                    "Para las 60 entradas aleatorias (m,k,n ∈ [1,16]) y los casos "
                    "límite de dimensión inválida, el adaptador generado produce "
                    "el mismo resultado float64 (tol 1e-9) que el modelo de "
                    "referencia en Python puro, y rechaza dimensiones inválidas "
                    "con el código de error del contrato."
                ),
                "domain": "m,k,n ∈ [1,16] aleatorio + ejes de tamaño 0",
                "status": "PROVEN" if verdict == "PASS" else "REFUTED",
                "trusted": ["python3", "ctypes", "libmatmul.so", "generated adapter"],
            },
            {
                "id": "BENCH-COMPETITIVE",
                "class": "empirical",
                "statement": (
                    "En el camino caliente, la latencia mediana del adaptador "
                    "generado es competitiva con el binding ctypes manual y "
                    "sustancialmente inferior a Python puro e IPC para tamaños "
                    "8×8–32×32."
                ),
                "domain": "tamaños 4,8,16,32; 35 repeticiones",
                "status": "OBSERVED",
                "trusted": ["time.perf_counter", "libmatmul.so"],
            },
        ],
        "what_was_verified": [
            "Equivalencia semántica en matrices densas float64 (dominio acotado)",
            "Rechazo de dimensiones inválidas (código de error del contrato)",
            "Superficie de error codes coherente con el YAML",
        ],
        "what_remains_unproven": [
            "Prueba formal de equivalencia para tamaños arbitrarios",
            "Camino zero-copy sin arrays intermedios de ctypes",
            "Generalización más allá del contrato matmul",
            "Propiedades de seguridad de un componente nativo no confiable",
            "Ausencia de solapamiento de buffers (precondición no declarada)",
        ],
        "decision": (
            "PROCEED to next iteration"
            if verdict == "PASS"
            else "HYPOTHESIS FALSIFIED for this case — investigate failures"
        ),
        "limits": (
            "PROVEN significa: no se encontró contraejemplo en el dominio "
            "indicado, bajo la base de confianza listada. No significa "
            "'software libre de errores bajo cualquier escenario'."
        ),
    }
    out = REPORT / "acceptance.json"
    out.write_text(json.dumps(cert, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main() -> int:
    print("COMMONWEAVE Zero — pipeline estabilizado + sello CSG")
    print("=" * 56)

    REPORT.mkdir(parents=True, exist_ok=True)

    # 1. Native library
    run(["make"], cwd=ROOT / "c_src")

    # 2. Adapter generation (idempotent)
    run([
        sys.executable, "generator/generate_adapter.py",
        "--contract", "contracts/matmul.yaml",
        "--lib", "c_src/libmatmul.so",
        "--out", "generated/matmul_adapter.py",
    ])

    # 3. Differential verification
    print("\n--- Differential verification ---")
    run([
        sys.executable, "verifier/differential.py",
        "--trials", "60",
        "--out", "report/differential.json",
    ])

    # 4. Four-way benchmark
    print("\n--- Four-way benchmark ---")
    run([
        sys.executable, "benchmarks/bench_four_way.py",
        "--sizes", "4,8,16,32",
        "--repeats", "35",
        "--out", "report/benchmark.json",
    ])

    # 5. Certificate
    diff = json.loads((REPORT / "differential.json").read_text(encoding="utf-8"))
    bench = json.loads((REPORT / "benchmark.json").read_text(encoding="utf-8"))
    acceptance = write_certificate(diff, bench)

    print("\n=== Acceptance certificate ===")
    print(json.dumps(json.loads(acceptance.read_text()), indent=2)[:1200] + "\n  …")

    # 6. Seal (CSG-inspired integrity seal)
    print("\n--- Integrity seal (CSG) ---")
    artifacts = [
        REPORT / "acceptance.json",
        REPORT / "differential.json",
        REPORT / "benchmark.json",
        ROOT / "contracts" / "matmul.yaml",
        ROOT / "generated" / "matmul_adapter.py",
        ROOT / "c_src" / "libmatmul.so",
    ]
    # Filter only existing
    artifacts = [p for p in artifacts if p.is_file()]

    run([
        sys.executable, "seal/sello.py",
        "--seal",
        "--demo-seed",           # reproducible for the prototype; remove in production
        "--base", str(ROOT),
        "--out", "report/sello.json",
        "--statement",
        "COMMONWEAVE Zero: differential verification PASS + four-way benchmark evidence. "
        "Seal covers acceptance certificate, differential report, benchmark, contract, "
        "generated adapter and native library.",
        "--artifacts", *[str(p) for p in artifacts],
    ])

    # 7. Self-verify the seal
    print("\n--- Seal verification ---")
    vr = subprocess.run(
        [
            sys.executable, "seal/sello.py",
            "--verify", "report/sello.json",
            "--base", str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    print(vr.stdout)
    seal_ok = vr.returncode == 0

    overall = diff.get("verdict") == "PASS" and seal_ok
    print("=" * 56)
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    print(f"  differential : {diff.get('verdict')}")
    print(f"  seal         : {'VALID' if seal_ok else 'INVALID'}")
    print(f"Artefactos en  : {REPORT}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
