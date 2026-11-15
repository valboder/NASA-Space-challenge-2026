# API de caso compartido (P01)

`astronaut_id` identifica siempre al paciente. `operator_id` identifica al tripulante que actúa; ambos deben pertenecer a la misión. La identidad es declarada: esta API todavía no incorpora autenticación.

## Iniciar y continuar

`POST /api/emergency/button` mantiene sus campos anteriores y admite `operator_id` y `session_id` opcionales, tanto en JSON como en multipart de audio. Sin operador se usa el paciente, para conservar compatibilidad. Sin sesión se reutiliza el caso OPEN/GUIDANCE_GIVEN del paciente y misión, o se abre uno si no existe; con sesión se continúa exactamente ese caso, que debe pertenecer al paciente y estar en OPEN o GUIDANCE_GIVEN.

```json
{"astronaut_id": 1, "mission_id": 1, "operator_id": 2, "session_id": 10, "transcript": "Estoy ayudando al paciente"}
```

La respuesta mantiene los campos anteriores y añade `case`. Los reportes y guías quedan en el historial con operador y fecha. Si falla la transcripción, el cliente debe conservar el `session_id` retornado y enviarlo al reintentar como texto.

## Consultar y recuperar

`GET /api/emergency/sessions/<session_id>` devuelve paciente, operador a cargo, estado, versión, historial, últimos estados de pasos, mediciones vinculadas y última respuesta del asistente. La versión es el identificador del último evento, o cero si aún no hay eventos; no debe suponerse consecutiva por caso.

Ambos clientes deben conservar el identificador del caso y consultar esta ruta al abrirlo, después de una actualización y periódicamente mientras colaboran. No se añadieron WebSockets ni cambios de frontend. El listado existente `/api/emergency/sessions?astronaut_id=...` permite localizar sesiones.

## Registrar colaboración

`POST /api/emergency/sessions/<session_id>/events` requiere `operator_id`, `expected_version` y `kind`:

```json
{"operator_id": 2, "expected_version": 5, "kind": "TAKEOVER", "payload": {}}
```

- `TAKEOVER`: registra que el operador toma el relevo; no elimina colaboradores ni historial.
- `STEP`: payload `{"step_id": "check-breathing", "completed": true}`. El cliente debe mantener identificadores estables de tarea dentro del caso. Cada cambio se añade al historial; la vista `steps` muestra el último estado por identificador.
- `MEASUREMENT`: payload `{"observation_id": 123}`. Vincula una observación existente del paciente y misión al caso; no crea ni reevalúa mediciones. Ese ciclo completo pertenece a P02.

Devuelve HTTP 201 y la instantánea actualizada. Un conflicto de versión devuelve 409: consultar nuevamente, mostrar el cambio al operador y decidir si procede reenviar con la nueva versión. No reenviar ciegamente una decisión basada en información antigua.

Los reportes del botón son entradas adicionales al historial, no reemplazos de pasos, y no requieren expected_version. La atomicidad completa y recuperación de operaciones interrumpidas siguen en P07; los reintentos con clave están cubiertos por P06.

Errores de pertenencia o formato: 400. Caso inexistente: 404. Caso finalizado o versión desactualizada: 409. Completar pasos no cambia el caso a RESOLVED.

## Almacenamiento y verificación

La nueva tabla `emergency_session_event` se crea al iniciar la aplicación mediante el esquema idempotente existente, sin resetear ni volver a sembrar la base. Los casos anteriores siguen disponibles; no se inventa historial previo de acciones no registradas.

Desde `backend/`: `python -m tests.test_shared_case`. Las pruebas usan una base temporal y no modifican la base del proyecto.

## Coherencia de estados (P04)

La respuesta del botón conserva `urgency`, `recommended_action` y `worst_passive_level`. La urgencia global toma la mayor prioridad de síntomas, gravedad pasiva y acción; puede ser `UNKNOWN` cuando no hay información suficiente. El peor nivel pasivo se calcula independientemente de la acción y puede ser `UNKNOWN`, nunca verde por defecto.

El campo nuevo `assessment` contiene `level`, `availability`, `evaluated_count`, `expected_count` y `note`. Disponibilidad: `UNAVAILABLE` sin riesgos evaluables, `PARTIAL` si falta alguno previsto y `COMPLETE` si todos los riesgos previstos tienen un nivel evaluable. COMPLETE se refiere a cobertura por riesgo, no a todas las mediciones ni a validación clínica. Un nivel GREEN con cobertura PARTIAL no confirma normalidad global. La selección de riesgos del botón no se amplió en P04: P03 sigue pendiente.

Las respuestas de consulta y recálculo de nave incluyen `assessment` y `worst_level`. `state` sigue siendo operacional: NORMAL con evaluación UNAVAILABLE no significa salud normal. La consulta devuelve el último estado operacional registrado y calcula una evaluación actual sin persistir alertas; `state_basis` explicita esta diferencia. El frontend debe mostrar la disponibilidad junto al estado y no pintar la salud de verde basándose solo en `state`.

El monitoreo devuelve `assessment` del paciente y `ship_assessment` de la tripulación junto al estado operacional. No se cambian las reglas de bloqueo ni se modifica el detector.

## Reintentos y episodios (P06)

Todos los POST `/api/` aceptan la cabecera `Idempotency-Key` (1–200 caracteres). El cliente debe generar una clave única por operación, guardarla antes de enviar y reutilizarla únicamente para reintentos de esa misma operación. Para compatibilidad, la cabecera es opcional: sin ella no se garantiza deduplicación de lecturas ni eventos repetidos.

La clave se conserva en SQLite, junto con una huella de ruta, parámetros y contenido. Un reintento devuelve el mismo cuerpo, código HTTP y tipo de contenido, con `Idempotency-Replayed: true`, incluso después de reiniciar. En audio la huella usa el contenido del archivo y los campos del formulario, no el separador variable del multipart. Cambiar el contenido o la ruta con la misma clave devuelve 409 `idempotency_key_conflict`. Una operación distinta necesita una clave nueva, aunque su valor medido sea idéntico.

Una operación reservada cuya respuesta aún no se guardó devuelve 409 `operation_pending`; puede estar en curso o interrumpida. No se debe reenviar con otra clave sin comprobar los efectos. No se implementó recuperación automática de ejecuciones parciales (P07). Las respuestas de error también se conservan si llegaron a completarse; corregir una solicitud requiere una clave nueva. Los registros no expiran automáticamente.

Los eventos del caso verifican idempotencia antes de comprobar expected_version: reenviar un evento ya completado devuelve su respuesta original aunque la versión actual haya avanzado. Para obtener el estado actual se debe consultar GET del caso.

El botón y el monitoreo reutilizan un caso OPEN o GUIDANCE_GIVEN por paciente y misión. Al finalizarlo (RESOLVED o ESCALATED, según el modelo actual), una nueva solicitud puede crear otro caso. No se fusionan ni eliminan automáticamente duplicados históricos.

Las evaluaciones no verdes actualizan una única alerta OPEN/ACKNOWLEDGED por paciente o hábitat, riesgo y destino. Cada evaluación permanece en `alert_evaluation`, consultable mediante `GET /api/emergency/alerts/<id>/history`. Un aumento de gravedad vuelve a poner la alerta en OPEN; repetir la misma gravedad conserva ACKNOWLEDGED. Tras resolver explícitamente la alerta, una nueva evaluación anormal abre otro episodio. Una lectura verde no cierra por sí sola el caso ni confirma recuperación.

Pruebas: `python -m tests.test_idempotency` (8 escenarios nuevos y las 4 regresiones de caso compartido heredadas). No se incorporan canales de notificación ni autenticación en P06.
