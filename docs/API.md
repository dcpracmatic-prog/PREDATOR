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

El servidor estándar solo permite bind no-loopback cuando configuras `PREDATOR_API_TOKEN`. En ese caso todos los endpoints salvo `GET /health` requieren `Authorization: Bearer <token>`. Define `PREDATOR_CORS_ORIGINS` como lista separada por comas de origins exactos permitidos; origins no permitidos se rechazan y sin allowlist no se habilita CORS. Los adaptadores stdlib y FastAPI limitan el cuerpo de cada petición a 1 MiB. En ASGI configura `PREDATOR_API_HOST` al host de bind para que la fábrica también rechace hosts no-loopback sin token; el despliegue ASGI debe configurar TLS/red perimetral en el servidor o proxy.

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

## Ejemplo

```bash
curl -s http://127.0.0.1:8080/v1/audit -H 'Content-Type: application/json' -d '{
  "graph": {"n": 4, "edges": [[0,1],[1,2],[2,3]]},
  "method": "auto",
  "budget_ms": 50,
  "sign": true
}'
```
