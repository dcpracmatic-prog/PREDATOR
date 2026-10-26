# PREDATOR HTTP API

Fachada B2B sobre el planificador y los informes firmables.

## Arranque

```bash
# stdlib (sin dependencias extra)
predator-api --host 127.0.0.1 --port 8080
# Alias legacy conservado para despliegues existentes
ztge-api --host 127.0.0.1 --port 8080

# opcional FastAPI
pip install -e ".[api]"
uvicorn predator.api.app:create_app --factory --host 0.0.0.0 --port 8080
```

### Seguridad al exponer la API

El servidor estándar solo permite bind no-loopback cuando configuras `PREDATOR_API_TOKEN`. En ese caso todos los endpoints salvo `GET /health` requieren `Authorization: Bearer <token>`. Define `PREDATOR_CORS_ORIGINS` como lista separada por comas de origins exactos permitidos; origins no permitidos se rechazan y sin allowlist no se habilita CORS. Los adaptadores stdlib y FastAPI limitan el cuerpo de cada petición según la memoria disponible: reservan aproximadamente 128× el tamaño del JSON para parseo/representación del grafo, con un mínimo operativo de 1 byte y tope de 64 MiB (si no se puede detectar memoria, el fallback es 1 MiB). El límite de vértices y aristas se adapta además a la memoria disponible y nunca supera los máximos que acepta MORPH. Las proporciones de memoria por nodo/arista son heurísticas, no mediciones de RSS ni una garantía de que toda carga quepa. Puedes fijar `PREDATOR_MAX_REQUEST_BYTES` (1 a 67,108,864 bytes) para adaptar el límite a una carga medida; se aplica a ambos adaptadores. `predator-hardware-profile --output profile.json` mide tamaños y presupuestos candidatos en el host y no cambia automáticamente los presupuestos de solicitudes. En ASGI configura `PREDATOR_API_HOST` al host de bind para que la fábrica también rechace hosts no-loopback sin token; el despliegue ASGI debe configurar TLS/red perimetral en el servidor o proxy.

```bash
export PREDATOR_API_TOKEN='un-secreto-largo-desde-tu-gestor-de-secretos'
export PREDATOR_CORS_ORIGINS='https://app.example.com'
predator-api --host 0.0.0.0 --port 8080
```

Firma de auditorías (opcional):

```bash
export ZTGE_HMAC_SECRET='hex:<64-hex-chars>'
```

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Liveness |
| GET | `/v1/status` | Motor + MORPH + contratos |
| GET | `/openapi.json` | OpenAPI 3.1 |
| POST | `/v1/plan` | Conjunto independiente + traza |
| POST | `/v1/audit` | Informe `ztge.audit.v1` (+ sobre firmado) |

Especificación: [`openapi/openapi.yaml`](../openapi/openapi.yaml) · [`openapi/openapi.json`](../openapi/openapi.json).

Esquemas de informe: [`schemas/ztge_audit_report.schema.json`](../schemas/ztge_audit_report.schema.json),
[`schemas/ztge_signed_envelope.schema.json`](../schemas/ztge_signed_envelope.schema.json).

La API rechaza tipos incorrectos sin coerción silenciosa: `n`, endpoints, `budget_ms`, `seed`, `auto_n_threshold` y `k_core_k` deben ser enteros JSON (sin booleanos, decimales ni cadenas numéricas); `seed` debe ser no negativo. `directed`, `sign` e `include_dense` deben ser booleanos. El límite de tamaño del cuerpo se valida antes de parsear JSON en ambos adaptadores; el servidor stdlib exige un único `Content-Length` decimal y rechaza `Transfer-Encoding: chunked` porque no implementa decodificación chunked.

## Ejemplo

```bash
curl -s http://127.0.0.1:8080/v1/audit -H 'Content-Type: application/json' -d '{
  "graph": {"n": 4, "edges": [[0,1],[1,2],[2,3]]},
  "method": "auto",
  "budget_ms": 50,
  "sign": true
}'
```


### Perfilado local de hardware

```bash
predator-hardware-profile --sizes 256,768,1600 --budgets-ms 25,100,250 --output hardware-profile.json
```

El informe detecta CPU/memoria visible al proceso, disponibilidad de MORPH y mide validez, tamaño de solución y tiempo de pared para cada punto del barrido. Los presupuestos candidatos son empíricos para ese host y esos grafos de calibración; no prueban optimalidad ni fuerzan el presupuesto de producción.
