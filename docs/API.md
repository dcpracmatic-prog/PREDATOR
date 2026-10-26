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


### Envío incremental a MORPH (opt-in)

`POST /v1/plan/native-file` recibe `application/json` en bloques, escribe el cuerpo a un archivo temporal, verifica `X-Content-SHA256` (SHA-256 del cuerpo crudo) y delega el parseo de `graph.n`/`graph.edges` al lector nativo de `dump_morph`. La ruta evita listas de aristas y objetos `Graph` en Python y está disponible por defecto; requiere `MORPH_DUMP_BIN` con soporte `--json`, `method="morph"`, grafo no dirigido y sin self-loops. El límite se calcula por petición como 80% del espacio libre de la carpeta temporal dividido entre `PREDATOR_NATIVE_MAX_UPLOADS` (2 por defecto; máximo 8), con techo absoluto de 50 GiB. `PREDATOR_NATIVE_MAX_REQUEST_BYTES` puede reducirlo, nunca elevarlo por encima del presupuesto de almacenamiento; si no se puede consultar el filesystem se usa un fallback de 128 MiB. El cliente debe enviar Content-Length; ambos adaptadores rechazan longitudes desconocidas y transferencia chunked.

Los límites nativos de vértices/aristas se calculan con la RAM disponible para el proceso (heurística: mitad de RAM disponible y presupuestos aproximados de 512 bytes/vértice y 128 bytes/arista), limitados a los máximos duros de MORPH: 2 millones de vértices y 10 millones de aristas. `PREDATOR_NATIVE_MAX_VERTICES` y `PREDATOR_NATIVE_MAX_EDGES` permiten bajar esos límites. La heuristic no garantiza RSS; el grafo además requiere CSR, heap/estructuras del solver y tiempo. `PREDATOR_NATIVE_MAX_CONCURRENT` limita solver concurrente (1 por defecto), y `PREDATOR_NATIVE_TIMEOUT_S` tiene default 300 s (rango 1–3600). `PREDATOR_NATIVE_MAX_STDOUT_BYTES` y `PREDATOR_NATIVE_MAX_STDERR_BYTES` limitan salida (32 MiB/1 MiB por defecto, techos 128 MiB/8 MiB). El control de subidas concurrentes se fija al inicio; configure variables antes de iniciar el proceso.

El techo de 50 GiB es una capacidad máxima de transporte/almacenamiento, no significa que MORPH pueda resolver cualquier grafo de ese tamaño. Revise espacio temporal, RAM/CPU, límites de proceso y concurrencia del host que ejecuta PREDATOR. Además, servidores proxy, CDN/Cloudflare y plataformas de hosting pueden imponer límites de cuerpo o duración menores; configúrelos por separado. Los topes son de admisión, no garantía de RSS ni de calidad/optimalidad. SHA-256 comprueba integridad, no autentica al cliente; use bearer token/TLS en despliegues remotos.
