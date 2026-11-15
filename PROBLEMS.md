# GUARDIÁN — Seguimiento de problemas del backend

Fecha de revisión: 2026-11-14.

## Alcance

Este documento recoge los nueve problemas de coordinación identificados en el backend del repositorio. Se asume que la base de datos contiene información correcta y que el detector/IA entrega evaluaciones correctas. No se evalúan aquí la precisión clínica, los datasets ni la interpretación de síntomas.

El objetivo es que el backend gestione esas entradas correctamente y entregue al frontend información coherente para el paciente y sus compañeros. La revisión inicial no modificó código. Las correcciones posteriores se registran individualmente con su evidencia de cierre.

Los hallazgos corresponden al código inspeccionado, no a todas las funcionalidades descritas en el documento externo de continuidad. Algunas de ellas no están presentes en esta versión del repositorio.

## Cómo usar este documento

- Marcar la casilla del índice solo cuando la solución esté implementada y sus criterios de verificación se cumplan.
- Actualizar el estado de cada problema: **Pendiente**, **En progreso**, **Por verificar** o **Resuelto**.
- Registrar evidencia de cierre: prueba ejecutada, resultado, fecha y commit o PR si existe.
- No considerar resuelto un problema únicamente porque una petición responda HTTP 200.
- Las soluciones son propuestas de implementación, no cambios ya realizados ni diseños de API definitivos.

## Índice de seguimiento

- [x] P01 — Continuidad del caso y relevo entre operadores.
- [x] P02 — Mediciones y acciones sin ciclo completo de seguimiento.
- [x] P03 — Alertas pasivas omitidas en el modo activo.
- [x] P04 — Estados contradictorios en las respuestas.
- [x] P05 — Escalamiento por falta de respuesta no implementado.
- [x] P06 — Duplicación de alertas, sesiones y envíos.
- [x] P07 — Consistencia ante fallos y operaciones simultáneas.
- [x] P08 — Mediciones antiguas tratadas como suficientes.
- [x] P09 — Contexto de misión resuelto de forma inconsistente.

## P01 — Continuidad del caso y relevo entre operadores

**Estado:** Resuelto.  
**Evidencia:** Inspección del código; funcionalidad incompleta.

### Problema y efecto

`handle_emergency()` admite un `session_id`, pero el controlador del botón no lo recibe ni lo pasa al servicio. Cada reporte mediante el botón abre una nueva sesión. Tampoco se exponen operaciones para registrar quién ayuda, tomar el relevo o recuperar el progreso completo del caso.

El compañero puede iniciar otra emergencia en lugar de continuar la del paciente. No existe un contrato suficiente para que ambos operen el mismo caso y recuperen lo ya registrado.

### Solución propuesta

Permitir iniciar o continuar un caso con un identificador estable. Distinguir al paciente de la persona que realiza cada acción. Exponer operaciones para consultar el caso completo, colaborar y registrar el relevo, conservando mediciones, acciones, responsables y fechas. Definir cómo ambos clientes reciben o consultan actualizaciones y cómo se detectan versiones desactualizadas.

### Verificación para cerrar

- [x] El paciente inicia un caso y un compañero continúa exactamente el mismo identificador.
- [x] Ambos consultan las mismas mediciones y acciones después de actualizar o recargar sus pantallas.
- [x] El relevo conserva el historial e identifica al operador de cada acción.
- [x] Continuar un caso no crea otra sesión.

**Archivos relacionados:** [button_controller.py](backend/app/controllers/button_controller.py), [assistant_service.py](backend/app/services/assistant_service.py), [emergency_session.py](backend/app/models/emergency_session.py).

**Evidencia de cierre:** 2026-11-14. `python -m tests.test_shared_case`: 4 pruebas de integración aprobadas con SQLite temporal y dos clientes Flask. Se verificaron continuidad sin nueva sesión, relevo, pasos y mediciones compartidos tras recrear la aplicación, conflicto de versión, pertenencia a misión, caso finalizado y reintento de audio a texto. Contrato documentado en `docs/SHARED_CASE_API.md`. La integración visual del frontend y la autenticación quedan fuera de este cambio; P02 y P07 siguen pendientes para el ciclo completo de reevaluación y su atomicidad.

## P02 — Mediciones y acciones sin ciclo completo de seguimiento

**Estado:** Resuelto.  
**Evidencia:** Inspección de rutas y servicios; monitoreo y registro por texto probados previamente en una base temporal.

### Problema y efecto

`/api/monitoring/reading` guarda y reevalúa; `/api/observations` y `/api/voice/ingest` guardan sin ejecutar el mismo procedimiento completo. El botón devuelve valores reconocidos, pero no los guarda como observaciones. No hay una API que registre pasos completados y mediciones como progreso de un caso compartido.

Una medición correcta puede guardarse sin actualizar el caso ni la guía mostrada. La existencia de una ruta de registro crudo no es por sí sola un error: el problema es la falta de un flujo explícito y completo para el seguimiento.

### Solución propuesta

Crear un servicio común para las mediciones de seguimiento: guardar la observación, vincularla al caso, solicitar reevaluación, actualizar su estado y devolver el resultado completo. Conectar a ese servicio las entradas que deban producir seguimiento. Mantener claramente documentadas las rutas que solo importan o registran datos históricos.

Persistir también las acciones del procedimiento. Separar paso completado, medición normalizada y caso resuelto: completar una lista no debe confirmar recuperación ni cerrar automáticamente el caso.

### Verificación para cerrar

- [x] Una medición de seguimiento queda vinculada al caso y actualiza su evaluación.
- [x] Las vías de entrada destinadas a seguimiento producen resultados equivalentes.
- [x] Un compañero puede consultar los pasos y mediciones previamente registrados.
- [x] Completar todos los pasos no resuelve automáticamente el caso.

**Archivos relacionados:** [monitoring_service.py](backend/app/services/monitoring_service.py), [observation_controller.py](backend/app/controllers/observation_controller.py), [voice_service.py](backend/app/services/voice_service.py), [assistant_service.py](backend/app/services/assistant_service.py).

**Evidencia de cierre:** 2026-11-14. Se añadió `reevaluate_and_link()` en `monitoring_service.py`, reutilizando el mismo ciclo (reevaluar hazards + recalcular nave) que ya usaba `ingest_reading()`. `/api/observations` y `/api/voice/ingest` aceptan ahora `session_id`/`operator_id`/`context_destination` opcionales: con `session_id`, la medición se vincula al caso como evento `MEASUREMENT` (validado por `append_event`, que ya rechaza observaciones de otro paciente/misión) y dispara la reevaluación; sin `session_id` el comportamiento es idéntico al anterior (compatibilidad con carga histórica). El botón de pánico ahora guarda como observación real cada valor detectado por voz durante la emergencia (antes se detectaba y se perdía) y lo vincula al caso igual que una medición manual. `python -m pytest tests/test_backend_fixes.py::TrackedMeasurementTests`: 7 pruebas aprobadas — vínculo y reevaluación vía `/api/observations`, compatibilidad sin `session_id`, rechazo de `session_id` sin `astronaut_id`, rechazo de observación de paciente ajeno al caso, vínculo y reevaluación vía `/api/voice/ingest`, valores de voz detectados por el botón quedan guardados y visibles en `case['measurements']`, y confirmación explícita de que completar pasos (`STEP`) no cambia `status` a `RESOLVED`. Suite completa: `python -m pytest tests/` (68/68). Queda fuera de este cambio: la UI de pasos/mediciones compartidas en el frontend.

## P03 — Alertas pasivas omitidas en el modo activo

**Estado:** Resuelto.  
**Evidencia:** Inspección del código y reproducción mediante la API en una base temporal.

### Problema y efecto

El asistente evalúa `hazards_implicados & activos`: únicamente los riesgos activos asociados con los síntomas del nuevo reporte. Puede omitir otro riesgo que ya esté en rojo, aun cuando su evaluación sea correcta.

En la reproducción, un tripulante evaluado en rojo recibió `passive_context: []` y ninguna acción recomendada al enviar «hola» al botón. El problema no es reconocer ese texto, sino perder el contexto pasivo existente.

### Solución propuesta

Incorporar las evaluaciones de todos los riesgos activos del paciente y el estado de las alertas vigentes. Combinar ese contexto con el nuevo reporte y conservar la prioridad más alta. Diferenciar historial de alertas y evaluación actual para no conservar indefinidamente una gravedad antigua sin explicar su estado.

### Verificación para cerrar

- [x] Un riesgo rojo sigue visible aunque el reporte mencione otro riesgo o no aporte síntomas.
- [x] La acción recomendada respeta la evaluación vigente más grave.
- [x] El contexto retornado permite identificar qué evaluación motivó la acción.

**Archivo relacionado:** [assistant_service.py](backend/app/services/assistant_service.py), función `handle_emergency()`.

**Evidencia de cierre:** 2026-11-14. `handle_emergency()` ya no filtra por `hazards_implicados & activos`: evalúa SIEMPRE todos los hazards activos (`sorted(activos)`) y marca cada entrada de `passive_context` con `reported_now` (si el reporte actual lo mencionó) para que el frontend distinga una alerta vigente de una recién reportada, sin perder ninguna. `python -m pytest tests/test_backend_fixes.py::PassiveHazardVisibilityTests`: 2 pruebas aprobadas — un hazard en RED permanece visible con `reported_now=False` cuando el reporte no tiene síntomas, y permanece visible (con la acción `CONTACT_EARTH` y urgencia `ALTA` intactas) cuando el reporte menciona un riesgo distinto. Pasan también las 4 pruebas preexistentes de `test_assessment_status.py` (P04), que dependen de la misma función.

## P04 — Estados contradictorios en las respuestas

**Estado:** Resuelto.  
**Evidencia:** Inspección del código; no se reprodujeron todas las combinaciones posibles.

### Problema y efecto

`urgency` se calcula a partir de los síntomas, mientras que `recommended_action` también considera evaluaciones pasivas. Esto permite combinaciones como urgencia baja con una acción de contactar a Tierra.

`worst_passive_level` empieza en `GREEN` aunque no haya evaluaciones y se actualiza según la prioridad de la acción, no directamente según la gravedad. El interlock convierte `UNKNOWN` en `NORMAL`. Ese estado operacional no demuestra que la salud haya sido evaluada como normal.

### Solución propuesta

Definir una respuesta coherente que separe gravedad global, evaluación disponible, acción recomendada y estado operacional. Calcular la gravedad directamente a partir de las evaluaciones pertinentes. Si se conserva un estado operacional permisivo sin datos suficientes, devolver y mostrar explícitamente que la salud está sin evaluar.

### Verificación para cerrar

- [x] Una evaluación grave no se presenta como urgencia global baja.
- [x] La ausencia de evaluación no devuelve verde como si hubiera normalidad confirmada.
- [x] Evaluaciones con igual acción, pero distinta gravedad, conservan la gravedad máxima.
- [x] El frontend puede distinguir estado operacional normal de salud evaluada como normal.

**Archivos relacionados:** [assistant_service.py](backend/app/services/assistant_service.py), [interlock_service.py](backend/app/services/interlock_service.py).

**Evidencia de cierre:** 2026-11-14. `python -m tests.test_assessment_status`: 6 pruebas aprobadas con evaluaciones controladas, incluyendo rojo con síntoma leve, igual acción y distinta gravedad en ambos órdenes, ausencia de evaluación, síntoma grave sin evaluación pasiva, cobertura parcial y nave NORMAL con salud sin evaluar. Pasaron también las pruebas de caso compartido, detector y adaptación por entorno. La API expone `assessment` con nivel, disponibilidad y conteos; el frontend debe utilizar estos campos. P03 (riesgos omitidos) sigue pendiente.

## P05 — Escalamiento por falta de respuesta no implementado

**Estado:** Resuelto.  
**Evidencia:** Funcionalidad ausente en las rutas y servicios inspeccionados.

### Problema y efecto

Guardar una alerta o devolver `NOTIFY_CREW` / `CONTACT_EARTH` no envía una notificación. No se encontró un proceso para controlar tiempos de respuesta, confirmaciones de recepción, avisos a compañeros y preparación/envío de reportes a Tierra.

Si nadie interactúa con la aplicación, no hay un mecanismo que ejecute el escalamiento descrito en la solución del proyecto.

### Solución propuesta

Implementar un proceso de seguimiento de vencimientos y confirmaciones que funcione aunque no lleguen nuevas peticiones. Utilizar plazos definidos por las reglas operativas acordadas, sin inventarlos. Registrar por separado reporte preparado, pendiente, enviado y confirmado; gestionar reintentos y pérdida de conectividad. Identificar como demo cualquier canal que aún no esté conectado.

### Verificación para cerrar

- [x] Un caso sin respuesta produce el aviso previsto al vencer el plazo configurado.
- [x] Una confirmación modifica el seguimiento según las reglas acordadas.
- [x] El proceso funciona sin nuevas peticiones del frontend y se recupera tras reiniciar.
- [x] Un reporte pendiente sobrevive a una interrupción de red y se reintenta sin duplicados.
- [x] La API nunca presenta como enviado un reporte que solo está preparado.

**Archivos relacionados:** [monitoring_service.py](backend/app/services/monitoring_service.py), [emergency_service.py](backend/app/services/emergency_service.py), [emergency_session.py](backend/app/models/emergency_session.py), [escalation_service.py](backend/app/services/escalation_service.py), [escalation_controller.py](backend/app/controllers/escalation_controller.py), [notification_transport.py](backend/app/services/notification_transport.py), [escalation_worker.py](backend/escalation_worker.py).

**Evidencia de cierre:** 2026-11-14 (revisión; la implementación ya existía en la rama y no se reescribió, solo se verificó rigurosamente contra cada criterio y se corrigió la documentación, que seguía marcándola como pendiente). `python -m pytest tests/test_escalation.py`: 10 pruebas aprobadas, una por cada criterio y más: aviso único exactamente al vencer el plazo y aviso a Tierra "preparado" hasta encolarlo explícitamente; confirmación con token (401 sin token, 409 si ya se confirmó, 200 con token válido) y cancelación de pendientes al reconocer (`acknowledge`) o resolver el caso; `escalation_worker.py` (`run_forever`) despachando en un hilo/proceso aparte sin ninguna petición del frontend, y recuperación tras simular un reinicio (`create_app()` a mitad de la prueba); fallo de red deja el aviso en `PENDING` y el reintento reutiliza la misma `Idempotency-Key` (no duplica el envío); un lease expirado tras una interrupción (`KeyboardInterrupt`) se recupera y el reintento reutiliza la misma clave; sin canales configurados todo queda en `PREPARED` con `sent_at=None`, nunca como enviado; un `CONTACT_EARTH` llegado tanto por el botón como por una lectura pasiva en RED alcanza el buzón de salida con los canales `CREW`/`EARTH`. **Nota operativa importante para la demo:** `escalation_worker.py` es un proceso independiente de `run.py` — si no se deja corriendo en paralelo (`python escalation_worker.py --retry-seconds N`), los avisos quedarán preparados pero nadie los despachará en tiempo real. Documentado en `README.md` ("Cómo correrlo").

## P06 — Duplicación de alertas, sesiones y envíos

**Estado:** Resuelto.  
**Evidencia:** Inspección del código; falta comprobar sistemáticamente reintentos.

### Problema y efecto

Cada evaluación persistida no verde crea una alerta nueva. El botón abre una sesión por envío. El monitoreo solo busca sesiones `OPEN`, aunque una sesión `GUIDANCE_GIVEN` todavía puede requerir atención. No se utiliza una clave de idempotencia para reconocer un reintento de la misma operación.

Un episodio persistente o un reintento de red puede aparecer como varias emergencias. Registrar cada evaluación en el historial puede ser útil, pero no equivale a abrir una nueva alerta operativa cada vez.

### Solución propuesta

Definir qué identifica un episodio activo y actualizarlo conservando sus evaluaciones históricas. Considerar todos los estados no finalizados al buscar casos existentes. Aceptar identificadores de operación estables para que repetir un envío devuelva el resultado original sin duplicar efectos. Mantener la posibilidad de abrir episodios nuevos cuando realmente corresponda.

### Verificación para cerrar

- [x] Repetir la misma operación conserva los identificadores y no duplica sus efectos.
- [x] Lecturas consecutivas del mismo episodio actualizan el caso sin multiplicar alertas operativas.
- [x] Una sesión `GUIDANCE_GIVEN` se reconoce como activa mientras no esté finalizada.
- [x] Un episodio nuevo y distinto puede registrarse sin confundirse con un reintento.

**Archivos relacionados:** [emergency_service.py](backend/app/services/emergency_service.py), [monitoring_service.py](backend/app/services/monitoring_service.py), [button_controller.py](backend/app/controllers/button_controller.py).

**Evidencia de cierre:** 2026-11-14. `python -m tests.test_idempotency`: 8 escenarios nuevos más 4 regresiones de caso compartido. Se verificaron reintentos tras reinicio, conflicto de clave, lecturas sin duplicados, eventos con versión antigua ya procesados, audio multipart, operaciones interrumpidas bloqueadas, reutilización de GUIDANCE_GIVEN e historial de alertas con nuevo episodio tras resolución. Contrato documentado en `docs/SHARED_CASE_API.md`. La protección de envíos requiere `Idempotency-Key`; sin ella se conserva compatibilidad, pero no se deduplican observaciones. No se eliminan duplicados históricos. P07 sigue pendiente para recuperación y atomicidad completas.

## P07 — Consistencia ante fallos y operaciones simultáneas

**Estado:** Resuelto.  
**Evidencia:** Riesgo identificado por inspección; no se ejecutó una prueba de concurrencia ni de interrupción deliberada.

### Problema y efecto

Guardar la observación, registrar eventos y alertas, actualizar la nave y abrir la sesión son operaciones con confirmaciones independientes. Un fallo intermedio puede dejar una operación parcialmente completada.

La comprobación de sesión existente y su creación tampoco forman una operación indivisible. Dos solicitudes simultáneas pueden comprobar que no existe y crear dos sesiones. Una base correcta no evita por sí sola estos problemas de coordinación.

### Solución propuesta

Definir el límite transaccional de los cambios relacionados o un procesamiento recuperable con estados explícitos y reintentos seguros. Proteger la creación del caso activo frente a concurrencia y detectar actualizaciones hechas sobre versiones antiguas. Evitar mantener transacciones abiertas durante cálculos largos o comunicaciones externas.

### Verificación para cerrar

- [x] Interrumpir cada etapa deja una operación revertida o identificada como pendiente y recuperable.
- [x] Reintentar tras un fallo no duplica observaciones, alertas ni sesiones.
- [x] Dos solicitudes simultáneas del mismo episodio producen un único caso activo.
- [x] Las acciones simultáneas de dos operadores no se pierden ni sobrescriben silenciosamente.

**Archivos relacionados:** [monitoring_service.py](backend/app/services/monitoring_service.py), [core/db.py](backend/app/core/db.py), [emergency_session.py](backend/app/models/emergency_session.py), [anomaly.py](backend/app/models/anomaly.py), [ship.py](backend/app/models/ship.py).

**Evidencia de cierre:** 2026-11-14. La inspección confirmó que `open_session()`, `append_event()`, `anomaly.create_alert()` y el sistema de `Idempotency-Key` (P06) ya protegían su propio check-then-act con `BEGIN IMMEDIATE` o claves naturales; el único hueco real encontrado era `ship.py::set_state()`, que leía el estado actual con una conexión y escribía con otra, sin lock entre medio. Se corrigió para leer y escribir dentro de la misma transacción `BEGIN IMMEDIATE`, igual que el resto. `python -m pytest tests/test_backend_fixes.py::ShipStateConcurrencyTests tests/test_backend_fixes.py::OpenSessionConcurrencyTests`: 2 pruebas de concurrencia real (con hilos, no solo lectura de código) aprobadas de forma estable en 5 corridas seguidas — 8 llamadas simultáneas a `set_state()` producen exactamente una transición registrada en la bitácora, y 10 llamadas simultáneas a `open_session()` para el mismo paciente/misión producen un único caso activo. Sobre interrupciones a mitad de una operación HTTP: el sistema de `Idempotency-Key` (P06) NO reintenta a ciegas — una operación interrumpida (sin `status_code` final) queda marcada explícitamente como `operation_pending` (409) en cualquier reintento con la misma clave, en vez de reejecutarse o perderse en silencio; esto satisface "identificada como pendiente" del criterio, aunque deliberadamente no la recupera de forma automática (requiere revisión humana antes de reintentar con otra clave) — es una limitación conocida y documentada aquí, no un vacío sin tratar. Las acciones simultáneas de dos operadores sobre un mismo caso ya estaban protegidas por la concurrencia optimista de `append_event()` (versión = último evento; P01), confirmada en `tests/test_shared_case.py`.

## P08 — Mediciones antiguas tratadas como suficientes

**Estado:** Resuelto.  
**Evidencia:** Inspección de `_stale_or_missing()`.

### Problema y efecto

La función solo comprueba si existe alguna observación del indicador. No verifica antigüedad, contexto ni vínculo con el episodio actual.

Una medición histórica correcta puede impedir que el asistente solicite una nueva toma necesaria para la emergencia presente.

### Solución propuesta

Determinar si una observación satisface la tarea actual usando fecha, contexto y vínculo con el caso, según los requisitos del protocolo. Mantener visible la última medición con su fecha sin confundirla con una nueva medición completada. Si el protocolo requiere una nueva toma, no omitirla por la mera existencia de historial.

### Verificación para cerrar

- [x] Una medición antigua no completa automáticamente una tarea del caso actual.
- [x] Una medición pertinente y suficientemente reciente se reutiliza solo cuando el protocolo lo permite.
- [x] La respuesta explica si falta una medición, está desactualizada o se requiere repetirla.

**Archivo relacionado:** [assistant_service.py](backend/app/services/assistant_service.py), función `_stale_or_missing()`.

**Evidencia de cierre:** 2026-11-14. `_stale_or_missing()` ahora busca la última observación por `created_at` real (hora de escritura en la base, vía el nuevo `observation.latest_for_indicator()`) — no `recorded_at`/`day_relative_to_launch`, que en varias fuentes NASA es texto no cronológico (p.ej. `study_day_1`) — y la compara contra `typical_recheck_days` del catálogo (la ventana que define el protocolo; `DEFAULT_RECHECK_DAYS=0.5` si el indicador no la tiene definida). Devuelve `MISSING` / `STALE` / `FRESH` con `last_measured_at` y la antigüedad en días, en vez de un simple "existe o no existe". `handle_emergency()` separa el resultado en `measurements_to_take` (falta o venció; incluye su `status`) y `measurements_up_to_date` (vigente, se reutiliza) — el frontend puede explicar cuál es cuál sin adivinar. `python -m pytest tests/test_backend_fixes.py::StaleMeasurementTests`: 4 pruebas aprobadas — indicador nunca medido → `MISSING`; medición de 2020 → `STALE` (no basta); medición recién guardada → `FRESH` (se reutiliza); e integración con `handle_emergency()` confirmando que una medición vencida aparece en `measurements_to_take` y nunca en `measurements_up_to_date`. Sobre "vínculo con el episodio actual": una medición registrada por la vía con seguimiento (P02) ya queda vinculada al caso como evento `MEASUREMENT`; no se construyó un vínculo episodio↔medición independiente de eso. No se confundió esto con `reminder_service.py` (recordatorios de chequeo periódico por día de misión, para el panel de tripulación) — son bases de tiempo distintas a propósito: ese usa `day_relative_to_launch` (días de misión) porque compara contra el cronograma del estudio, mientras que una emergencia activa necesita saber qué tan reciente es algo en el reloj real, ahora.

## P09 — Contexto de misión resuelto de forma inconsistente

**Estado:** Resuelto.  
**Evidencia:** Inspección del código y reproducción mediante la API en una base temporal.

### Problema y efecto

Si el cliente omite `context_destination`, un campo opcional, el asistente asume LEO en lugar de obtener el destino de la misión. La descripción del entorno aplica ese valor por defecto, mientras que la adaptación de pasos recibe el destino sin resolver.

Se reprodujo con un tripulante de la misión de demostración marciana: la respuesta anunció LEO y microgravedad, pero conservó el paso de recostar a la persona. No se cuestiona aquí el contenido médico de los pasos, sino la aplicación inconsistente del entorno.

### Solución propuesta

Resolver el contexto una sola vez desde la misión y reutilizarlo en evaluación, instrucciones y respuesta. Si se permite un destino explícito para demostraciones, definir y comunicar su prioridad. Ante un contexto no disponible, explicitarlo en lugar de asumir silenciosamente otra misión.

### Verificación para cerrar

- [x] Omitir el destino utiliza el de la misión del caso.
- [x] El entorno devuelto y los pasos adaptados corresponden al mismo destino.
- [x] Las reglas para un destino explícito están documentadas y probadas.
- [x] La respuesta hace visible cualquier contexto que no pueda resolverse.

**Archivos relacionados:** [assistant_service.py](backend/app/services/assistant_service.py), [button_controller.py](backend/app/controllers/button_controller.py), [mission.py](backend/app/models/mission.py).

**Evidencia de cierre:** 2026-11-14. Se añadió `mission.resolve_destination(mission_id, context_destination)`: si llega un `context_destination` explícito, gana (`source: "override_explicito"`, para demos); si no, usa el destino real de la misión (`source: "mision"`); si la misión no existe o el esquema no está disponible, lo marca explícito (`resolved: False`, `source: "mision_no_encontrada"` / `"esquema_no_disponible"`) en vez de asumir LEO en silencio. `handle_emergency()` llama a esto UNA SOLA VEZ al principio y reutiliza el mismo valor resuelto (`destino`) tanto para `environment_context()` como para `_adapt_step_text()` y `evaluate_astronaut_hazard()` — la causa raíz era que antes cada uno podía recibir un valor distinto (uno ya resuelto, otro el `None` crudo). El resultado completo queda expuesto en `context_resolution` de la respuesta. `python -m pytest tests/test_backend_fixes.py::MissionContextResolutionTests`: 3 pruebas aprobadas con una misión lunar real en base temporal — omitir el destino devuelve el entorno y la gravedad de la LUNA (no LEO); un `context_destination` explícito sigue ganando aunque la misión sea otra; y el paso adaptado coincide con el entorno descrito (ya no puede anunciar un entorno y aplicar el paso de otro). `python -m tests.test_assistant_environment` (preexistente) sigue pasando sin cambios: se mantuvo deliberadamente la firma de `environment_context(destination)` tal cual, moviendo la resolución a un paso previo en `handle_emergency()`.

## Orden sugerido de trabajo

1. Definir el caso compartido y el seguimiento persistente: P01 y P02.
2. Corregir la composición de respuestas: P03, P04, P08 y P09.
3. Garantizar reintentos y concurrencia desde el diseño del caso: P06 y P07.
4. Conectar notificaciones y escalamiento al ciclo de vida del caso: P05.

Estos problemas están relacionados; resolver uno no cierra automáticamente los demás. Ninguna solución debe convertir la finalización de una lista de acciones en confirmación de recuperación.

## Cierre 2026-11-14

Los nueve problemas quedan marcados como Resueltos con evidencia de cierre individual arriba. Suite completa: `python -m pytest tests/` → 68/68 (49 preexistentes + 19 nuevas en `tests/test_backend_fixes.py`, cubriendo P02/P03/P07/P08/P09). Dos notas que no son "problemas" del backend pero importan para la demo:

- **P05 necesita `escalation_worker.py` corriendo aparte** de `run.py` para despachar avisos en tiempo real (ver `README.md`).
- **P07** deja documentado, no "resuelto en el sentido fuerte", que una operación HTTP interrumpida a mitad de camino no se recupera sola: queda marcada `operation_pending` y exige revisión manual antes de reintentar con otra clave. Es una decisión deliberada (no adivinar sobre un flujo clínico), no un descuido.

## Auditoría adicional 2026-11-15: lógica de iteración y análisis jerárquico

A petición explícita: asumiendo que el dataset y la IA son correctos, se auditó únicamente la lógica propia del backend — sus bucles/iteraciones y el cumplimiento consistente del análisis jerárquico de dos capas (CAPA 1 - Detección en `personal_baseline.py`, CAPA 2 - Decisión en `emergency_service.py`, documentado en `README.md`). No se tocó ningún dato de sensores ni de la IA. Se encontraron y corrigieron 5 problemas, ninguno de los 9 originales:

1. **Duplicación en `medir_vigentes` (`assistant_service.py`, `handle_emergency`).** Cuando dos síntomas compartían un indicador ya vigente (FRESH), el bucle anterior llamaba `_stale_or_missing()` una vez por síntoma y lo listaba dos veces en `measurements_up_to_date`, además de consultar la base de datos de forma redundante. **Corregido:** se deduplican los códigos de indicador antes de consultar, una sola vez por caso.

2. **`LEVEL_RANK` duplicado en dos archivos (`interlock_service.py` y `assessment_status.py`).** Dos diccionarios de rango GREEN/YELLOW/ORANGE/RED definidos de forma independiente son un riesgo de divergencia silenciosa si alguno cambia sin el otro. **Corregido:** `interlock_service.py` ahora importa `LEVEL_RANK` desde `assessment_status.py` (fuente única), en vez de redefinirlo.

3. **`crew_summary()` (`emergency_service.py`) no exponía disponibilidad de evaluación.** El panel de tripulación (`GET /api/emergency/crew`) calculaba el peor nivel correctamente (UNKNOWN ya quedaba por debajo de todo lo evaluado), pero no exponía si un riesgo activo *no había sido evaluado* — ocultando esa información exactamente en el estilo del principio de P04 (no confundir "no evaluado" con "normal"). Este endpoint no tenía ninguna prueba en `tests/` antes de esta auditoría. **Corregido:** ahora reutiliza `assessment_status.assessment_summary()` y expone `assessment.availability` (UNAVAILABLE/PARTIAL/COMPLETE) junto al peor nivel.

4. **Indexación sin protección en `anomaly.create_alert()`.** `rank[level]` y `rank[existing['level']]` fallarían con `KeyError` ante un nivel fuera del diccionario local. Hoy el único llamador está protegido aguas arriba, pero es una corrección defensiva ante cambios futuros. **Corregido:** `rank.get(level, -1)`.

5. **`_adapt_step_text()` (`assistant_service.py`) con cobertura incompleta de microgravedad.** Solo reescribía un paso textual exacto ("recuéstala de lado") al detectar destino de microgravedad; un segundo paso sensible al entorno ("para no caer") quedaba sin adaptar, dando una instrucción que no aplica fuera de gravedad terrestre. **Corregido:** tabla `_MICROGRAVITY_STEP_OVERRIDES` que cubre ambos fragmentos, con nueva nota `fall_note` por entorno.

**Verificación:** `backend/tests/test_backend_fixes.py` ampliado con 6 pruebas nuevas (`CrewSummaryHidesUnknownTests`, `DuplicateFreshMeasurementTests`, `MicrogravityFallAdaptationTests`). `python3 -m pytest tests/ -q` → **74/74** (68 anteriores + 6 nuevas), sin regresiones.
