#!/usr/bin/env python3
"""
COMMONWEAVE Zero — Sello de Integridad (inspirado en CSG / sello-integridad)

Attestación criptográfica de los artefactos de verificación y benchmark.
- Ed25519 para firmas
- SHA3-256 para huellas de contenido
- Cadena de sellos verificable
- Sin claves privadas en los artefactos públicos

Diseño alineado con la intención de CSG: el resultado de la verificación
deja de ser un JSON editable y pasa a ser un objeto firmado y verificable
por terceros.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


def sha3_256_hex(data: bytes) -> str:
    return hashlib.sha3_256(data).hexdigest()


def file_digest(path: Path) -> str:
    return sha3_256_hex(path.read_bytes())


@dataclass
class Firmante:
    """Identidad que firma (equivalente conceptual al Firmante de CSG)."""
    nombre: str
    public_key_b64: str
    # private key only kept in memory / keystore; never written to seal


@dataclass
class Sello:
    """Un sello individual sobre un artefacto o sobre un conjunto de artefactos."""
    version: str
    proyecto: str
    firmante: str
    public_key_b64: str
    timestamp_utc: str
    artifacts: List[Dict[str, str]]  # [{path, sha3_256}]
    payload_hash: str                # hash del conjunto ordenado
    signature_b64: str
    statement: str


class SelloIntegridad:
    """
    Emisor y verificador de sellos.
    La clave privada se genera o se carga; nunca se incluye en el sello.
    """

    def __init__(self, nombre_firmante: str = "COMMONWEAVE-Zero", seed: Optional[bytes] = None):
        if seed is not None:
            # deterministic for reproducible demos (NOT for production)
            self._private = Ed25519PrivateKey.from_private_bytes(seed[:32].ljust(32, b"\0"))
        else:
            self._private = Ed25519PrivateKey.generate()
        self._public = self._private.public_key()
        self.nombre = nombre_firmante

    @property
    def public_key_b64(self) -> str:
        raw = self._public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode("ascii")

    def firmante_info(self) -> Firmante:
        return Firmante(nombre=self.nombre, public_key_b64=self.public_key_b64)

    def _canonical_payload(self, artifacts: List[Dict[str, str]], statement: str, ts: str) -> bytes:
        """Payload canónico que se firma (orden determinista)."""
        body = {
            "version": "1.0",
            "proyecto": "COMMONWEAVE-Zero",
            "firmante": self.nombre,
            "public_key_b64": self.public_key_b64,
            "timestamp_utc": ts,
            "artifacts": sorted(artifacts, key=lambda a: a["path"]),
            "statement": statement,
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def sellar(
        self,
        artifact_paths: List[Path],
        statement: str,
        base_dir: Optional[Path] = None,
    ) -> Sello:
        base = base_dir or Path.cwd()
        artifacts = []
        for p in artifact_paths:
            p = p.resolve()
            rel = str(p.relative_to(base)) if p.is_relative_to(base) else str(p)
            artifacts.append({"path": rel, "sha3_256": file_digest(p)})

        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload = self._canonical_payload(artifacts, statement, ts)
        payload_hash = sha3_256_hex(payload)
        signature = self._private.sign(payload)
        signature_b64 = base64.b64encode(signature).decode("ascii")

        return Sello(
            version="1.0",
            proyecto="COMMONWEAVE-Zero",
            firmante=self.nombre,
            public_key_b64=self.public_key_b64,
            timestamp_utc=ts,
            artifacts=artifacts,
            payload_hash=payload_hash,
            signature_b64=signature_b64,
            statement=statement,
        )

    @staticmethod
    def verificar(sello: Sello | Dict[str, Any], base_dir: Optional[Path] = None) -> Dict[str, Any]:
        """
        Verifica:
        1. Firma Ed25519 del payload canónico.
        2. Que los SHA3 de los artefactos coinciden con los ficheros actuales.
        """
        if isinstance(sello, dict):
            s = Sello(**{k: sello[k] for k in Sello.__dataclass_fields__})
        else:
            s = sello

        base = base_dir or Path.cwd()
        result: Dict[str, Any] = {
            "signature_valid": False,
            "artifacts_intact": False,
            "details": [],
        }

        # Reconstruct canonical payload
        body = {
            "version": s.version,
            "proyecto": s.proyecto,
            "firmante": s.firmante,
            "public_key_b64": s.public_key_b64,
            "timestamp_utc": s.timestamp_utc,
            "artifacts": sorted(s.artifacts, key=lambda a: a["path"]),
            "statement": s.statement,
        }
        payload = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload_hash = sha3_256_hex(payload)
        if payload_hash != s.payload_hash:
            result["details"].append("payload_hash mismatch (tampered seal structure)")
            return result

        try:
            pub_raw = base64.b64decode(s.public_key_b64)
            public = Ed25519PublicKey.from_public_bytes(pub_raw)
            sig = base64.b64decode(s.signature_b64)
            public.verify(sig, payload)
            result["signature_valid"] = True
        except (InvalidSignature, Exception) as e:
            result["details"].append(f"signature verification failed: {e}")
            return result

        # Check artifact digests
        intact = True
        for art in s.artifacts:
            path = base / art["path"]
            if not path.is_file():
                intact = False
                result["details"].append(f"missing artifact: {art['path']}")
                continue
            current = file_digest(path)
            if current != art["sha3_256"]:
                intact = False
                result["details"].append(
                    f"digest mismatch: {art['path']} expected={art['sha3_256'][:16]}… got={current[:16]}…"
                )
        result["artifacts_intact"] = intact
        if intact and result["signature_valid"]:
            result["details"].append("seal valid: signature + all artifact digests match")
        return result


def write_sello(sello: Sello, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(sello)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sellar o verificar artefactos COMMONWEAVE")
    parser.add_argument("--seal", action="store_true", help="Crear sello")
    parser.add_argument("--verify", type=Path, help="Verificar un sello.json existente")
    parser.add_argument("--artifacts", nargs="+", type=Path, help="Ficheros a sellar")
    parser.add_argument("--statement", default="COMMONWEAVE Zero acceptance evidence")
    parser.add_argument("--out", type=Path, default=Path("report/sello.json"))
    parser.add_argument("--base", type=Path, default=None, help="Directorio base para paths relativos")
    parser.add_argument("--demo-seed", action="store_true", help="Usar seed fija (solo demo)")
    args = parser.parse_args()

    base = args.base or Path.cwd()

    if args.verify:
        data = json.loads(args.verify.read_text(encoding="utf-8"))
        result = SelloIntegridad.verificar(data, base_dir=base)
        print(json.dumps(result, indent=2))
        return 0 if result["signature_valid"] and result["artifacts_intact"] else 1

    if args.seal:
        if not args.artifacts:
            parser.error("--seal requiere --artifacts")
        seed = b"COMMONWEAVE-ZERO-DEMO-SEED-v1" if args.demo_seed else None
        engine = SelloIntegridad(nombre_firmante="COMMONWEAVE-Zero", seed=seed)
        sello = engine.sellar(args.artifacts, args.statement, base_dir=base)
        write_sello(sello, args.out)
        print(f"Sello escrito: {args.out}")
        print(f"  firmante     : {sello.firmante}")
        print(f"  public_key   : {sello.public_key_b64[:32]}…")
        print(f"  artifacts    : {len(sello.artifacts)}")
        print(f"  payload_hash : {sello.payload_hash[:24]}…")
        # auto-verify
        vr = SelloIntegridad.verificar(sello, base_dir=base)
        print(f"  self-verify  : {vr}")
        return 0 if vr["signature_valid"] and vr["artifacts_intact"] else 1

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
