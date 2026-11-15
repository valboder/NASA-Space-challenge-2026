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
- [ ] P02 — Mediciones y acciones sin ciclo completo de seguimiento.
- [ ] P03 — Alertas pasivas omitidas en el modo activo.
- [x] P04 — Estados contradictorios en las respuestas.
- [ ] P05 — Escalamiento por falta de respuesta no implementado.
- [x] P06 — Duplicación de alertas, sesiones y envíos.
- [ ] P07 — Consistencia ante fallos y operaciones simultáneas.
- [ ] P08 — Mediciones antiguas tratadas como suficientes.
- [ ] P09 — Contexto de misión resuelto de forma inconsistente.

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

**Estado:** Pendiente.  
**Evidencia:** Inspección de rutas y servicios; monitoreo y registro por texto probados previamente en una base temporal.

### Problema y efecto

`/api/monitoring/reading` guarda y reevalúa; `/api/observations` y `/api/voice/ingest` guardan sin ejecutar el mismo procedimiento completo. El botón devuelve valores reconocidos, pero no los guarda como observaciones. No hay una API que registre pasos completados y mediciones como progreso de un caso compartido.

Una medición correcta puede guardarse sin actualizar el caso ni la guía mostrada. La existencia de una ruta de registro crudo no es por sí sola un error: el problema es la falta de un flujo explícito y completo para el seguimiento.

### Solución propuesta

Crear un servicio común para las mediciones de seguimiento: guardar la observación, vincularla al caso, solicitar reevaluación, actualizar su estado y devolver el resultado completo. Conectar a ese servicio las entradas que deban producir seguimiento. Mantener claramente documentadas las rutas que solo importan o registran datos históricos.

Persistir también las acciones del procedimiento. Separar paso completado, medición normalizada y caso resuelto: completar una lista no debe confirmar recuperación ni cerrar automáticamente el caso.

### Verificación para cerrar

- [ ] Una medición de seguimiento queda vinculada al caso y actualiza su evaluación.
- [ ] Las vías de entrada destinadas a seguimiento producen resultados equivalentes.
- [ ] Un compañero puede consultar los pasos y mediciones previamente registrados.
- [ ] Completar todos los pasos no resuelve automáticamente el caso.

**Archivos relacionados:** [monitoring_service.py](backend/app/services/monitoring_service.py), [observation_controller.py](backend/app/controllers/observation_controller.py), [voice_service.py](backend/app/services/voice_service.py), [assistant_service.py](backend/app/services/assistant_service.py).

**Evidencia de cierre:** Pendiente.

## P03 — Alertas pasivas omitidas en el modo activo

**Estado:** Pendiente.  
**Evidencia:** Inspección del código y reproducción mediante la API en una base temporal.

### Problema y efecto

El asistente evalúa `hazards_implicados & activos`: únicamente los riesgos activos asociados con los síntomas del nuevo reporte. Puede omitir otro riesgo que ya esté en rojo, aun cuando su evaluación sea correcta.

En la reproducción, un tripulante evaluado en rojo recibió `passive_context: []` y ninguna acción recomendada al enviar «hola» al botón. El problema no es reconocer ese texto, sino perder el contexto pasivo existente.

### Solución propuesta

Incorporar las evaluaciones de todos los riesgos activos del paciente y el estado de las alertas vigentes. Combinar ese contexto con el nuevo reporte y conservar la prioridad más alta. Diferenciar historial de alertas y evaluación actual para no conservar indefinidamente una gravedad antigua sin explicar su estado.

### Verificación para cerrar

- [ ] Un riesgo rojo sigue visible aunque el reporte mencione otro riesgo o no aporte síntomas.
- [ ] La acción recomendada respeta la evaluación vigente más grave.
- [ ] El contexto retornado permite identificar qué evaluación motivó la acción.

**Archivo relacionado:** [assistant_service.py](backend/app/services/assistant_service.py), función `handle_emergency()`.

**Evidencia de cierre:** Pendiente.

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

**Estado:** Pendiente.  
**Evidencia:** Funcionalidad ausente en las rutas y servicios inspeccionados.

### Problema y efecto

Guardar una alerta o devolver `NOTIFY_CREW` / `CONTACT_EARTH` no envía una notificación. No se encontró un proceso para controlar tiempos de respuesta, confirmaciones de recepción, avisos a compañeros y preparación/envío de reportes a Tierra.

Si nadie interactúa con la aplicación, no hay un mecanismo que ejecute el escalamiento descrito en la solución del proyecto.

### Solución propuesta

Implementar un proceso de seguimiento de vencimientos y confirmaciones que funcione aunque no lleguen nuevas peticiones. Utilizar plazos definidos por las reglas operativas acordadas, sin inventarlos. Registrar por separado reporte preparado, pendiente, enviado y confirmado; gestionar reintentos y pérdida de conectividad. Identificar como demo cualquier canal que aún no esté conectado.

### Verificación para cerrar

- [ ] Un caso sin respuesta produce el aviso previsto al vencer el plazo configurado.
- [ ] Una confirmación modifica el seguimiento según las reglas acordadas.
- [ ] El proceso funciona sin nuevas peticiones del frontend y se recupera tras reiniciar.
- [ ] Un reporte pendiente sobrevive a una interrupción de red y se reintenta sin duplicados.
- [ ] La API nunca presenta como enviado un reporte que solo está preparado.

**Archivos relacionados:** [monitoring_service.py](backend/app/services/monitoring_service.py), [emergency_service.py](backend/app/services/emergency_service.py), [emergency_session.py](backend/app/models/emergency_session.py). El proceso de envío y vencimientos está pendiente de implementar.

**Evidencia de cierre:** Pendiente.

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

**Estado:** Pendiente.  
**Evidencia:** Riesgo identificado por inspección; no se ejecutó una prueba de concurrencia ni de interrupción deliberada.

### Problema y efecto

Guardar la observación, registrar eventos y alertas, actualizar la nave y abrir la sesión son operaciones con confirmaciones independientes. Un fallo intermedio puede dejar una operación parcialmente completada.

La comprobación de sesión existente y su creación tampoco forman una operación indivisible. Dos solicitudes simultáneas pueden comprobar que no existe y crear dos sesiones. Una base correcta no evita por sí sola estos problemas de coordinación.

### Solución propuesta

Definir el límite transaccional de los cambios relacionados o un procesamiento recuperable con estados explícitos y reintentos seguros. Proteger la creación del caso activo frente a concurrencia y detectar actualizaciones hechas sobre versiones antiguas. Evitar mantener transacciones abiertas durante cálculos largos o comunicaciones externas.

### Verificación para cerrar

- [ ] Interrumpir cada etapa deja una operación revertida o identificada como pendiente y recuperable.
- [ ] Reintentar tras un fallo no duplica observaciones, alertas ni sesiones.
- [ ] Dos solicitudes simultáneas del mismo episodio producen un único caso activo.
- [ ] Las acciones simultáneas de dos operadores no se pierden ni sobrescriben silenciosamente.

**Archivos relacionados:** [monitoring_service.py](backend/app/services/monitoring_service.py), [core/db.py](backend/app/core/db.py), [emergency_session.py](backend/app/models/emergency_session.py), [anomaly.py](backend/app/models/anomaly.py), [ship.py](backend/app/models/ship.py).

**Evidencia de cierre:** Pendiente.

## P08 — Mediciones antiguas tratadas como suficientes

**Estado:** Pendiente.  
**Evidencia:** Inspección de `_stale_or_missing()`.

### Problema y efecto

La función solo comprueba si existe alguna observación del indicador. No verifica antigüedad, contexto ni vínculo con el episodio actual.

Una medición histórica correcta puede impedir que el asistente solicite una nueva toma necesaria para la emergencia presente.

### Solución propuesta

Determinar si una observación satisface la tarea actual usando fecha, contexto y vínculo con el caso, según los requisitos del protocolo. Mantener visible la última medición con su fecha sin confundirla con una nueva medición completada. Si el protocolo requiere una nueva toma, no omitirla por la mera existencia de historial.

### Verificación para cerrar

- [ ] Una medición antigua no completa automáticamente una tarea del caso actual.
- [ ] Una medición pertinente y suficientemente reciente se reutiliza solo cuando el protocolo lo permite.
- [ ] La respuesta explica si falta una medición, está desactualizada o se requiere repetirla.

**Archivo relacionado:** [assistant_service.py](backend/app/services/assistant_service.py), función `_stale_or_missing()`.

**Evidencia de cierre:** Pendiente.

## P09 — Contexto de misión resuelto de forma inconsistente

**Estado:** Pendiente.  
**Evidencia:** Inspección del código y reproducción mediante la API en una base temporal.

### Problema y efecto

Si el cliente omite `context_destination`, un campo opcional, el asistente asume LEO en lugar de obtener el destino de la misión. La descripción del entorno aplica ese valor por defecto, mientras que la adaptación de pasos recibe el destino sin resolver.

Se reprodujo con un tripulante de la misión de demostración marciana: la respuesta anunció LEO y microgravedad, pero conservó el paso de recostar a la persona. No se cuestiona aquí el contenido médico de los pasos, sino la aplicación inconsistente del entorno.

### Solución propuesta

Resolver el contexto una sola vez desde la misión y reutilizarlo en evaluación, instrucciones y respuesta. Si se permite un destino explícito para demostraciones, definir y comunicar su prioridad. Ante un contexto no disponible, explicitarlo en lugar de asumir silenciosamente otra misión.

### Verificación para cerrar

- [ ] Omitir el destino utiliza el de la misión del caso.
- [ ] El entorno devuelto y los pasos adaptados corresponden al mismo destino.
- [ ] Las reglas para un destino explícito están documentadas y probadas.
- [ ] La respuesta hace visible cualquier contexto que no pueda resolverse.

**Archivos relacionados:** [assistant_service.py](backend/app/services/assistant_service.py), [button_controller.py](backend/app/controllers/button_controller.py), [mission.py](backend/app/models/mission.py).

**Evidencia de cierre:** Pendiente.

## Orden sugerido de trabajo

1. Definir el caso compartido y el seguimiento persistente: P01 y P02.
2. Corregir la composición de respuestas: P03, P04, P08 y P09.
3. Garantizar reintentos y concurrencia desde el diseño del caso: P06 y P07.
4. Conectar notificaciones y escalamiento al ciclo de vida del caso: P05.

Estos problemas están relacionados; resolver uno no cierra automáticamente los demás. Ninguna solución debe convertir la finalización de una lista de acciones en confirmación de recuperación.
