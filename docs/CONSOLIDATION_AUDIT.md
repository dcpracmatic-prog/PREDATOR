# ZTGE — auditoría y consolidación

Fecha de revisión: 2026-10-20  
Rama de trabajo: `audit/ztge-consolidation`

## Estado observado

El repositorio ya reúne un SDK Python, una heurística nativa C++ (`MORPH`), verificadores de grafos, generación de informes y contratos declarativos. El objetivo de esta consolidación es convertir esa combinación en una librería reproducible, verificable y honesta sobre sus garantías.

## Hallazgos y riesgos que deben cerrarse

### P0 — Verificación real antes de declarar una versión consolidada

- CI comprobado en Python 3.10, 3.11 y 3.12: suite de pruebas, benchmark de humo, build de MORPH, smoke tests del CLI y wheel en entorno virtual limpio.
- La matriz verde valida estas plataformas y escenarios de regresión, no equivale a una auditoría de seguridad exhaustiva ni prueba de optimalidad global.

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

Asegurar y probar: nodos fuera de rango, aristas duplicadas, auto-bucles, grafo vacío, nodos aislados, entradas con tipos incorrectos, grafos dirigidos y entradas de gran tamaño. La capa Python valida nodos, pesos finitos y estructura; MORPH valida el archivo nativo y limita cabeceras a 2.000.000 de vértices y 10.000.000 de aristas para evitar reservas de memoria descontroladas. MORPH trabaja con grafos no dirigidos simples; la serialización debe conservar ese contrato.

### P2 — Empaquetado y experiencia de uso

- Mantener una sola ruta de instalación documentada y comprobar que la instalación editable y la instalación construida incluyen todos los paquetes requeridos.
- Evitar insertar rutas en `sys.path` en tiempo de ejecución cuando la instalación del paquete ya proporciona una importación estable; si se conserva el modo checkout, documentarlo y cubrirlo con pruebas.
- Añadir smoke tests del CLI y del artefacto de informe, además de las pruebas unitarias.

### P2 — Contratos y alcance del producto

- Separar claramente contratos activos, ejemplos y contratos experimentales. No anunciar generación/validación universal de adaptadores hasta que cada contrato tenga pruebas diferenciales ejecutables.
- El servicio HTTP/API B2B, la reconfiguración autónoma de redes y la ejecución de políticas de acceso no forman parte del paquete descrito actualmente; no presentarlos como funciones disponibles.

## Orden recomendado

1. Completado: matrix CI verde y corrección de fallos detectados.
2. Completado para casos de regresión: verificación HMAC/Ed25519, payloads manipulados y estructuras mal formadas.
3. Completado para los casos cubiertos: loaders Python, parámetros, salida MORPH corrupta, timeout de subprocess real y parser nativo .gph.
4. Completado en CI: construcción de wheel, instalación limpia y ejecución de los dos comandos CLI.
5. Completado como benchmark de humo, no como estudio de rendimiento publicable: semillas fijadas, n=256/768/1600, GWMIN/auto/MORPH cuando está disponible, validez, tiempo de pared total, tamaño de solución y fallback.
6. Pendiente antes de un release formal: auditoría de licencias/procedencia de `vendor/`, política de versiones y benchmarks extendidos/independientes.

## Criterio de aceptación para declarar “consolidado”

- CI verde en todas las versiones Python soportadas.
- Pruebas negativas para verificadores, fallbacks, entradas adversariales, respuesta nativa mal formada y timeout de proceso.
- Instalación limpia desde wheel y CLI operativos fuera del checkout.
- Informes reproducibles y verificables por un consumidor independiente.
- Benchmark de humo que distingue latencia de pared total, calidad y método/fallback efectivos; los benchmarks de producción más extensos siguen pendientes.
- Documentación consistente con comportamiento comprobado, sin atribuir optimalidad a una heurística ni garantías de seguridad no demostradas.
## Incidencia CI detectada y corrección aplicada

Los primeros seis checks fallaron al ejecutar `ztge-status`, después de que MORPH compilara correctamente y las dos pruebas existentes pasaran. Error observado: `ModuleNotFoundError: No module named 'ztge_status_entry'`. La causa era un punto de entrada de consola que referenciaba un módulo no incluido de forma importable en la instalación.

Corrección aplicada: el punto de entrada ahora apunta a `clan_subnet_detector.status_cli:main`. GitHub Actions confirmó después los seis jobs (Python 3.10, 3.11 y 3.12 en dos ejecuciones); los pasos de instalación, compilación MORPH, pruebas y smoke tests del CLI terminaron en verde.

## Hallazgos de auditoría de casos límite y evidencia de CI

- Corregido el subgrafo inducido no dirigido: antes insertaba dos veces cada arista almacenada en ambas listas de adyacencia, duplicando pesos. El conteo de aristas no dirigidas ahora cuenta los auto-bucles una sola vez y la densidad los excluye del numerador para no superar 1.
- Corregido el verificador de conjunto independiente para rechazar vértices con auto-bucle y nodos fuera de rango; GWMIN ya no selecciona vértices con auto-bucle.
- El verificador Ed25519 ahora trata una firma hexadecimal malformada o un hash no ASCII como verificación fallida, en lugar de propagar la excepción.
- Añadidas pruebas para loaders estáticos/temporales/NetFlow, entradas no finitas, pesos y tamaños no representables, IDs booleanos, grafos aleatorios con semillas fijas, salidas MORPH duplicadas/fuera de rango/no independientes, errores del ejecutable, timeout simulado y timeout de un ejecutable POSIX real.
- El parser C++ rechaza cabeceras negativas o demasiado grandes, aristas truncadas, vértices fuera de rango, self-loops, duplicados, recuentos incongruentes, tags desconocidos y argumentos de CLI inválidos. Las pruebas ejecutan el binario compilado en CI y requieren errores no-cero dentro de un timeout.
- Benchmark de humo: tamaños de 256, 768 y 1600 nodos; dos muestras por tamaño y método; reporta mediana, p95, máximo, validez, tamaño de solución, método resuelto y fallbacks. Los resultados se guardan como artefacto de CI por versión Python.

Evidencia más reciente observada: 90 pruebas pasan en Python 3.10, 3.11 y 3.12; en los mismos jobs pasaron el build MORPH, el benchmark de humo y la instalación/CLI desde wheel en entorno limpio. Esto permite revisar la rama para integración, pero no implica fuzzing ilimitado, una auditoría criptográfica externa ni pruebas de optimalidad.
