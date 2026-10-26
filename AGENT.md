# PREDATOR MCP — guía para agentes de IA

## Qué es PREDATOR

PREDATOR es un coprocesador local y embebible para grafos: recibe una representación acotada del grafo, ejecuta algoritmos de planificación/análisis y devuelve resultados estructurados que el agente puede verificar. Su interfaz MCP usa transporte `stdio` y adapta los mismos handlers validados de la API HTTP; no requiere enviar el grafo a un servicio remoto.

PREDATOR devuelve un conjunto independiente **válido**, pero no afirma que sea máximo ni óptimo. Mantén esa diferencia clara cuando expliques un resultado.

## División de responsabilidades

- **LLM = estratega:** identifica el problema, decide qué grafo representar, define qué significan nodos y aristas, selecciona el método/presupuesto y explica el resultado en contexto.
- **PREDATOR = motor de ejecución:** recibe la estructura explícita, calcula el conjunto independiente, lo verifica y puede producir un informe de auditoría.

**No resuelvas a mano la combinatoria pesada ni simules la búsqueda en texto.** Cuando la pregunta se traduzca a un problema de conjunto independiente, modela el grafo y delega el cálculo a `plan_independent_set`. Comprueba `verified` antes de usar el resultado como una solución válida. PREDATOR no determina por sí solo si el modelo del grafo representa correctamente la situación real.

## Tools disponibles

### `predator_status()`

No recibe parámetros. Devuelve el estado real del handler `/v1/status`, con campos superiores `engine`, `version`, `clan_version`, `morph` y `contracts`. Consulta este resultado para saber si el binario MORPH está disponible y qué contratos se distribuyen. La forma de `morph` depende del estado: puede incluir `available`, `binary` y `reason` o `warning`.

### `plan_independent_set(n, edges, directed=False, method="auto", budget_ms=100, seed=1, auto_n_threshold=1500)`

Calcula y verifica un conjunto independiente.

- `n` (entero, requerido): número de nodos. Numéralos consecutivamente de `0` a `n-1`.
- `edges` (lista de pares de enteros, requerida): cada arista es `[origen, destino]`; ambos extremos deben estar en `[0, n)`.
- `directed` (booleano, default `false`): indica si el grafo se interpreta como dirigido. El modelo y la verificación usan esta opción; el agente debe elegirla según el problema.
- `method` (default `"auto"`): `"auto"`, `"gwmin"` o `"morph"`.
- `budget_ms` (entero, default `100`, rango validado `[1, 600000]`): presupuesto solicitado al planificador; no es una garantía de tiempo máximo de pared.
- `seed` (entero, default `1`): semilla para el planificador/MORPH.
- `auto_n_threshold` (entero, default `1500`, mínimo `1`): umbral de tamaño que usa la política `auto` para elegir ruta.

Respuesta satisfactoria real: `{ "nodes": [...], "size": entero, "verified": booleano, "trace": {...} }`. `nodes` contiene los IDs elegidos; `size` es su cantidad; `verified` confirma que el verificador detectó que forman un conjunto independiente en el grafo recibido; `trace` informa la ruta/resolución utilizada y puede incluir datos de fallback. Si la validación falla, la tool produce un error (el handler HTTP subyacente devuelve `validation_error` y detalles), no un resultado válido con esos cuatro campos.

### `audit_graph(n, edges, directed=False, method="auto", budget_ms=100, seed=1, include_dense=True, k_core_k=3, graph_source=None, sign=True, key_id="hmac:default")`

Ejecuta la auditoría sobre el mismo tipo de grafo y devuelve un informe `ztge.audit.v1`.

- `n`, `edges`, `directed`, `method`, `budget_ms`, `seed`: mismos significados y defaults que en `plan_independent_set`.
- `include_dense` (booleano, default `true`): incluye el análisis de estructuras densas.
- `k_core_k` (entero, default `3`, mínimo `1`): parámetro `k` del análisis de k-core.
- `graph_source` (texto o `null`, default `null`): procedencia/descripción del grafo para el informe.
- `sign` (booleano, default `true`): solicita firma HMAC si `ZTGE_HMAC_SECRET` está configurada; si no hay secreto disponible, la respuesta queda sin firmar.
- `key_id` (texto, default `"hmac:default"`): identificador descriptivo de la clave, no es la clave secreta.

Respuesta satisfactoria real: `{ "report": {...}, "envelope": objeto_o_null, "signed": booleano }`. El `report` conserva el identificador `ztge.audit.v1`; `envelope` es un sobre firmado `ztge.envelope.v1` cuando se firmó y `null` en caso contrario. No afirmes que se firmó si `signed` no es `true`. Errores de validación se comunican como errores de tool.

## Instalación y registro MCP

Instala PREDATOR en el entorno de Python que vaya a usar el cliente MCP, incluyendo el extra MCP:

```bash
python -m pip install 'predator[mcp]'
```

El comando registrado por el paquete es `predator-mcp`. El cliente lo inicia como proceso local y se comunica por `stdio`. El comando debe estar en el `PATH` del proceso del cliente; si el cliente no hereda ese `PATH`, usa la ruta absoluta a `predator-mcp` o configura `command` como el intérprete Python con `args` apuntando a `-m predator.predator_server`.

### Claude Desktop

En el archivo de configuración MCP de Claude Desktop, agrega esta entrada bajo `mcpServers` (conserva las demás entradas que ya tengas):

```json
{
  "mcpServers": {
    "predator": {
      "command": "predator-mcp",
      "args": [],
      "env": {
        "ZTGE_HMAC_SECRET": "hex:<64-caracteres-hexadecimales>"
      }
    }
  }
}
```

### Cursor

En la configuración de proyecto `.cursor/mcp.json`, usa la misma estructura MCP:

```json
{
  "mcpServers": {
    "predator": {
      "command": "predator-mcp",
      "args": [],
      "env": {
        "ZTGE_HMAC_SECRET": "hex:<64-caracteres-hexadecimales>"
      }
    }
  }
}
```

Si `predator-mcp` no se encuentra desde el cliente, sustituye `command` y `args` por la ruta al Python del entorno donde instalaste el paquete, por ejemplo `"command": "/ruta/al/entorno/bin/python"`, `"args": ["-m", "predator.predator_server"]` (en Windows usa `python.exe` del entorno).

Usa el mecanismo de secretos del cliente o del sistema para inyectar `ZTGE_HMAC_SECRET`; no guardes una clave real en un archivo versionado. El ejemplo `hex:<...>` es solo un marcador. Si la variable se omite, `audit_graph` puede devolver el reporte sin firma aunque `sign=true`. El secreto HMAC debe ser compartido de forma segura con quien verificará el informe.

## Flujo recomendado

1. Llama a `predator_status()` y revisa la disponibilidad de MORPH. No supongas que el binario está instalado.
2. Traduce el problema a nodos y aristas; documenta qué representa cada uno. Valida que IDs estén en `0..n-1` y los extremos de aristas en rango.
3. Llama a `plan_independent_set(...)` con el método y presupuesto adecuados.
4. Comprueba `verified`. Si es `false` o la llamada falla, no presentes los nodos como una solución verificada.
5. Explica la traza y cualquier fallback. No describas un resultado heurístico como óptimo.
6. Llama a `audit_graph(...)` solo cuando necesites un informe estructurado y/o firma; confirma `signed=true` y que `envelope` no sea `null` antes de decir que está firmado.

## Garantías y límites

- **Heurística, no optimizador exacto:** `gwmin` es una heurística greedy; MORPH también es heurístico y no certifica optimalidad. `verified=true` valida independencia del conjunto, no que sea máximo ni que el grafo modelado sea correcto.
- **Presupuesto no es timeout duro de pared:** `budget_ms` es un presupuesto para el algoritmo. El arranque del proceso, el sistema operativo y otros costos pueden hacer que el tiempo total observado sea mayor.
- **Fallback por disponibilidad:** si el binario MORPH no existe o falla, la ruta de planificación puede degradar a GWMIN; revisa `trace` y `morph` en lugar de asumir qué motor corrió. En Termux o Windows el binario nativo puede no estar instalado o no ser compatible, así que debe esperarse esa degradación salvo que se haya compilado/configurado uno compatible.
- **HMAC y Ed25519 no son equivalentes:** la tool `audit_graph` firma por HMAC-SHA256 usando `ZTGE_HMAC_SECRET`; verificación requiere compartir el mismo secreto y no ofrece no repudio entre sus poseedores. El código de auditoría también tiene utilidades Ed25519 para firma/verificación con clave privada/pública, pero esta interfaz MCP no expone un parámetro para firmar directamente con Ed25519. No afirmes que `audit_graph` produjo una firma Ed25519.
- **Firma no certifica la verdad de entrada:** un sobre verifica integridad/autenticidad respecto de la clave usada; no demuestra que el grafo, la procedencia declarada o las afirmaciones de negocio sean verdaderas.
- **Privacidad local:** el transporte `stdio` opera entre procesos locales, pero la seguridad de la máquina, configuración del cliente, logs y gestión de secretos siguen siendo responsabilidad del despliegue.
