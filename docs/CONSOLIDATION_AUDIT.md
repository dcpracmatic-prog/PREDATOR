# ZTGE — auditoría y consolidación

Fecha de revisión: 2026-10-19  
Rama de trabajo: `audit/ztge-consolidation`

## Estado observado

El repositorio ya reúne un SDK Python, una heurística nativa C++ (`MORPH`), verificadores de grafos, generación de informes y contratos declarativos. El objetivo de esta consolidación es convertir esa combinación en una librería reproducible, verificable y honesta sobre sus garantías.

## Hallazgos y riesgos que deben cerrarse

### P0 — Verificación real antes de declarar una versión consolidada

- La documentación describe rutas de instalación y pruebas, pero el estado de GitHub Actions no se ha verificado desde esta auditoría. Se añade un workflow de CI para construir MORPH y ejecutar la suite en Python 3.10–3.12.
- El workflow debe pasar en GitHub antes de afirmar que la consolidación está validada. Esta edición no equivale a una ejecución de pruebas.

### P1 — Contrato de firma y verificación independiente

- La documentación define un hash canónico SHA-256 y firma HMAC-SHA256 o Ed25519. La revisión de documentación por sí sola no demuestra que el código rechace todos los casos alterados.
- Deben existir pruebas negativas para payload modificado, hash incorrecto, firma incorrecta, clave ausente, algoritmo/key-id no admitido y JSON malformado.
- HMAC requiere compartir un secreto; no ofrece no repudio. Ed25519 permite verificación pública, pero exige gestionar la clave privada y distribuir de forma fiable las claves públicas.
- El campo `content_hash` debe calcularse sobre una representación canónica única. La verificación debe reconstruir exactamente esa representación y rechazar campos/algoritmos ambiguos.

### P1 — Garantías del planificador

- `MORPH` se describe correctamente como heurística, no como optimizador exacto. El resultado debe verificarse siempre contra el grafo de entrada, incluso después de fallback.
- El presupuesto de tiempo no debe anunciarse como límite duro de tiempo de pared sin pruebas que lo demuestren: compilación, creación del proceso, serialización y planificación del sistema operativo pueden exceder el presupuesto interno.
- La selección `auto` debe exponer método solicitado, método realmente ejecutado, motivo del fallback y disponibilidad del binario en los metadatos de auditoría.

### P1 — Integridad de la entrada del grafo

Asegurar y probar: nodos fuera de rango, aristas duplicadas, auto-bucles, grafo vacío, nodos aislados, entradas con tipos incorrectos, grafos dirigidos (rechazo explícito si no se soportan) y entradas de gran tamaño. La normalización no debe cambiar silenciosamente la semántica del grafo.

### P2 — Empaquetado y experiencia de uso

- Mantener una sola ruta de instalación documentada y comprobar que la instalación editable y la instalación construida incluyen todos los paquetes requeridos.
- Evitar insertar rutas en `sys.path` en tiempo de ejecución cuando la instalación del paquete ya proporciona una importación estable; si se conserva el modo checkout, documentarlo y cubrirlo con pruebas.
- Añadir smoke tests del CLI y del artefacto de informe, además de las pruebas unitarias.

### P2 — Contratos y alcance del producto

- Separar claramente contratos activos, ejemplos y contratos experimentales. No anunciar generación/validación universal de adaptadores hasta que cada contrato tenga pruebas diferenciales ejecutables.
- El servicio HTTP/API B2B, la reconfiguración autónoma de redes y la ejecución de políticas de acceso no forman parte del paquete descrito actualmente; no presentarlos como funciones disponibles.

## Orden recomendado

1. Obtener CI verde en la rama de consolidación y corregir los fallos reales que aparezcan.
2. Auditar los módulos de firma/verificación y añadir pruebas negativas.
3. Auditar la validación del grafo y la frontera Python/C++ con casos adversariales.
4. Verificar instalación desde wheel en un entorno limpio y los comandos CLI.
5. Ejecutar benchmarks reproducibles con semillas fijadas y reportar calidad, latencia total, método efectivo y dispersión; separar resultados sintéticos de resultados de producción.
6. Revisar licencias y procedencia de `vendor/`, y fijar el proceso de releases/versionado.

## Criterio de aceptación para declarar “consolidado”

- CI verde en todas las versiones Python soportadas.
- Suite de pruebas que cubra verificadores, fallback, errores de proceso y firmas inválidas.
- Instalación limpia desde wheel y CLI operativos sin `PYTHONPATH` manual.
- Informes reproducibles y verificables por un consumidor independiente.
- Benchmarks que distingan latencia interna de latencia total y calidad de la solución.
- Documentación consistente con el comportamiento comprobado, sin atribuir optimalidad a una heurística ni garantías de seguridad no demostradas.
## Incidencia CI detectada y corrección aplicada

Los primeros seis checks fallaron al ejecutar `ztge-status`, después de que MORPH compilara correctamente y las dos pruebas existentes pasaran. Error observado en los logs: `ModuleNotFoundError: No module named 'ztge_status_entry'`. La causa era un punto de entrada de consola que referenciaba un módulo no incluido de forma importable en la instalación.

Corrección aplicada en la rama de consolidación: el punto de entrada ahora apunta a `clan_subnet_detector.status_cli:main`, módulo incluido en el paquete instalado. La corrección debe considerarse provisional hasta que una nueva ejecución de CI confirme los seis jobs. El hecho de que las dos pruebas pasaran no equivale a validar el comportamiento completo del motor.
