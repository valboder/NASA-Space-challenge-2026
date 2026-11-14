# GUARDIÁN — Validación del modelo

Este documento reporta lo que el sistema **sí** y **no** puede demostrar con los
datos disponibles. Está escrito para que cualquiera pueda reproducir los números
y para que nadie tenga que confiar en nuestra palabra.

Reproducir todo:
```bash
cd backend
python -m data.seed.seed_all
python -m tests.test_personal_baseline
python -m tests.test_assistant_environment
```

---

## 1. Por qué descartamos el enfoque supervisado inicial

La primera versión generaba datos sintéticos etiquetados y entrenaba un
RandomForest para predecir la situación y la acción. Medido:

| Modelo | Acciones correctas |
|---|---|
| RandomForest, 200 árboles | 99.60 % |
| Un solo árbol de decisión, profundidad 4 | 91.40 % |
| Un solo árbol de decisión, profundidad 3 | 82.40 % |

Con split de 3 grupos y validación cruzada el número no baja:

| Protocolo | Resultado |
|---|---|
| Validación (400 casos) | 100.00 % |
| Prueba (400 casos) | 99.75 % |
| Validación cruzada, 5 pliegues | 99.70 % ± 0.19 |

**El problema no era el protocolo de evaluación, era el origen de los datos.**
De las 12 combinaciones variable/situación del generador, **9 tenían rangos que
no se solapan con el rango normal** (p.ej. arritmia: pulso 135–175 contra un
normal de 48–96). Las clases eran perfectamente separables, así que el modelo
solo estaba redescubriendo las reglas `if/elif` que el propio equipo escribió
para etiquetar. Entrenamiento y prueba salían del mismo generador, por lo que
ningún split podía revelar el problema.

Dos detalles más que lo confirman:

- **El contexto de misión aportaba 0.42 %** de la importancia en la decisión.
  Al revisar el generador, solo la radiación de fondo cambiaba por destino; las
  otras 7 variables eran estadísticamente idénticas en órbita, Luna, Marte y
  tránsito. La afirmación "analiza según el contexto de la misión" no estaba
  respaldada por los datos.
- La tasa de falsos negativos era **0.00 %** (0 de 129 emergencias). Ningún
  sistema real nunca se pierde una emergencia; ese cero era la señal de que los
  datos eran ficticios.

---

## 2. Una confusión de variables que habría invalidado el resultado

Los estudios de reposo de la NASA registran la **postura** del sujeto al momento
de la toma. Su distribución por fase:

| Fase | Supine | Tilt | −6° |
|---|---|---|---|
| PRE_TEST | 20 | 20 | 0 |
| IN_TEST | 0 | 16 | 16 |
| POST_TEST | 16 | 36 | 20 |

`Supine` no aparece en IN_TEST y `−6°` no aparece en PRE_TEST. Comparar las
fases sin filtrar habría hecho que el modelo detectara **la postura del sujeto,
no su adaptación fisiológica**. La única postura presente en las tres fases es
`Tilt`, así que todas las comparaciones de abajo están restringidas a ella.

---

## 3. Qué separan realmente las variables NASA

Pregunta: ¿distinguen el estado de reposo prolongado (análogo de microgravedad)
del estado basal? AUC de 0.5 equivale a lanzar una moneda.

| Variable | Fuente | n (basal / durante) | Media basal | Media durante | AUC | p |
|---|---|---|---|---|---|---|
| ANP en plasma | MR001G | 15 / 10 | 23.2 | 25.5 | **0.487** | 0.934 |
| ACTH en plasma | MR001G | 15 / 10 | 93.4 | 100.2 | **0.513** | 0.934 |
| Calcio sérico | OSDR LSDS-8 | 12 / 16 | 9.83 | 9.66 | 0.357 | 0.207 |
| Albúmina sérica | OSDR LSDS-8 | 12 / 16 | 4.65 | 4.54 | 0.380 | 0.292 |
| Creatinina sérica | OSDR LSDS-8 | 12 / 16 | 1.07 | 1.07 | 0.503 | 1.000 |

(Mann-Whitney bilateral. Para el CMP la comparación es antes del vuelo `L-`
contra después `R+`, que es la estructura que trae ese dataset.)

**Conclusión: ninguna de estas variables separa la condición con estos datos.**
Con 10 a 16 sujetos y AUC en el nivel del azar, cualquier clasificador entrenado
sobre ellas estaría ajustando ruido. Por eso GUARDIÁN **no** usa un modelo
poblacional supervisado como vía principal.

### La señal que sí tiene respaldo estadístico: degradación del sueño

Tendencia a lo largo de los días de reposo, medida **dentro de cada sujeto**
(actigrafía, BRSMAct). La columna "detector" es lo que marca GUARDIÁN con su
criterio de señal-sobre-ruido; las dos últimas son una prueba de rangos de
Spearman hecha aparte para contrastarlo:

| Sujeto | Indicador | n días | Theil-Sen /día | Detector | Spearman ρ | p | ¿Coincide? |
|---|---|---|---|---|---|---|---|
| C1G0001 | Eficiencia de sueño | 60 | −0.141 | **WARN** | −0.50 | 0.0000 | sí |
| C1G0001 | Duración de sueño | 60 | −0.667 | **WARN** | −0.58 | 0.0000 | sí |
| C1G0001 | Latencia de sueño | 60 | +0.700 | **WARN** | +0.57 | 0.0000 | sí |
| C1G0002 | Eficiencia de sueño | 55 | −0.025 | ok | −0.07 | 0.5877 | sí |
| C1G0002 | Duración de sueño | 55 | −0.390 | ok | −0.26 | 0.0550 | sí |
| C1G0002 | Latencia de sueño | 54 | +0.400 | **WARN** | +0.36 | 0.0067 | sí |
| C1G0003 | Eficiencia de sueño | 52 | −0.092 | ok | −0.16 | 0.2699 | sí |
| C1G0003 | Duración de sueño | 52 | −0.706 | **WARN** | −0.52 | 0.0001 | sí |
| C1G0003 | Latencia de sueño | 52 | +0.727 | **WARN** | +0.55 | 0.0000 | sí |

**9 de 9 coincidencias, cero desacuerdos.** Todo lo que el detector marcó tiene
p < 0.05, y todo lo que dejó pasar tiene p ≥ 0.05. Esto es la evidencia concreta
de que el detector **no está sobre-alertando**: su criterio de señal-sobre-ruido
—que no asume ninguna distribución ni calcula valores p— reproduce exactamente
lo que dice una prueba de rangos estándar.

Los **tres** sujetos muestran degradación significativa del sueño durante el
reposo prolongado, aunque en indicadores distintos: C1G0001 en los tres,
C1G0002 solo en latencia, C1G0003 en duración y latencia. Fisiológicamente es
coherente con lo que se espera del reposo prolongado. Con n=3 no se generaliza a
una población, pero la señal es real y medible en cada individuo — que es
precisamente el nivel al que opera GUARDIÁN.

---

## 4. El diseño que sí se sostiene: línea base personal

La pregunta clínica real no es poblacional ("¿los astronautas en general cambian
de ANP?") sino individual: **"¿este tripulante se está saliendo de SU propio
normal?"**. Eso se responde con n=1 por persona, que es exactamente la situación
de una tripulación de cuatro, y es cómo trabaja la medicina espacial: la NASA usa
las mediciones pre-vuelo de cada tripulante como su referencia individual.

Tres señales independientes, cada una con su propio requisito de datos:

| Señal | Qué necesita | Qué aporta |
|---|---|---|
| 1. Desviación de la línea base personal | ≥3 mediciones pre-vuelo | Sensibilidad individual |
| 2. Rango de referencia clínico | 1 medición + rango publicado | Especificidad |
| 3. Tendencia intra-sujeto | ≥10 puntos en la fase actual | Detección temprana y lenta |

Ninguna requiere etiquetas inventadas. Cada veredicto reporta en
`signals_used` cuáles pudo calcular, y devuelve `NOT_EVALUABLE` en lugar de
adivinar cuando no alcanza para ninguna.

### Rangos de referencia usados

Vienen **dentro del propio dataset de NASA OSDR** (columnas `range_min` /
`range_max`), no los inventamos:

| Indicador | Rango | Unidad |
|---|---|---|
| Albúmina sérica | 3.6 – 5.1 | g/dL |
| Calcio sérico | 8.6 – 10.4 | mg/dL |
| Creatinina sérica | 0.5 – 1.35 | mg/dL |
| Glucosa sérica | 65 – 99 | mg/dL |

Varios indicadores traen más de un rango (referencias distintas por sexo). Se
toma **el más amplio** a propósito: un valor fuera incluso del rango más
permisivo es inequívocamente anormal, así que esta señal queda específica. La
sensibilidad la aporta la señal 1, no esta.

---

## 5. Dos errores que encontramos y corregimos

Quedan documentados porque son el tipo de falla que pasa desapercibida y produce
alertas sin sentido.

**a) Escala de dispersión colapsada.** Con 3 mediciones basales casi idénticas
(albúmina 5.0, 5.0, 4.9) el MAD cae a cero y cualquier cambio mínimo da un z
absurdo. Un caso real: pasar a 4.6 g/dL —clínicamente trivial, dentro del rango
normal 3.6–5.1— salía como **8.5 desviaciones**. Corregido con un piso de escala
anclado al ancho del rango de referencia (ancho/6 ≈ 1 desviación poblacional).
Tras la corrección, ese mismo caso da z = −1.6 y se reporta como normal.

**b) Orden cronológico incorrecto.** En varias fuentes NASA el campo de fecha es
texto (`'+45d_relative_to_launch'`), así que ordenar por él daba un orden
alfabético. El sistema tomaba como "valor actual" una medición del día +45 en
lugar de la del día +194, y generaba una alerta roja falsa. Corregido ordenando
por `day_relative_to_launch`.

Además, una desviación que **sigue dentro** del rango clínico normal no puede
escalar a rojo: "se movió respecto de sí mismo pero sigue sano" es un aviso, no
una emergencia.

**c) Pendiente real pero clínicamente irrelevante (falso positivo de tendencia).**
Al construir la demo de episodios de emergencia (`seed_emergency_episodes.py`)
apareció un tercer caso, más sutil que los dos anteriores. Un tripulante
"control" (MARS-03, calcio estable entre 9.7 y 9.9 mg/dL) salía en **WARN**
en vez de GREEN. La causa: con 12 puntos repartidos en muchos días, una
pendiente diminuta (~0.001 mg/dL/día) multiplicada por un periodo largo supera
el piso de ruido de la señal 3 (`efecto > SNR·MAD`), aunque la pendiente en sí
no signifique nada clínicamente.

Se corrigió con **dos filtros adicionales**, cada uno independiente del
anterior, de modo que una tendencia solo se reporta si pasa los tres:

- **Monotonía real — tau de Kendall.** `_kendall_tau()` mide si la relación
  entre día y valor es realmente consistente (cerca de +1 o −1) o es apenas
  ruido con un sesgo casual (cerca de 0). Medido en este caso: tau = 0.16,
  muy por debajo del umbral `TREND_TAU_MIN = 0.20` que sí cumplen las
  tendencias reales de sueño de la sección 3 (tau ≥ 0.57 en todos los casos
  que el detector marcó).
- **Significancia clínica — fracción del rango de referencia.** Incluso con
  monotonía real, el efecto acumulado debe ser al menos `TREND_CLINICAL_FRAC
  = 0.25` (25 %) del ancho del rango de referencia publicado para contar como
  "material". El caso MARS-03: efecto acumulado 0.2 mg/dL contra un rango de
  referencia de 1.8 mg/dL de ancho (8.6–10.4) → 11 %, por debajo del 25 %. No
  se reporta como tendencia.

Tras agregar ambos filtros, se repitió la validación de la sección 3 (9/9
contra Spearman) para confirmar que **no se perdió ninguna detección real**:
sigue en 9/9. Los tres filtros —ruido, monotonía, significancia clínica— son
condiciones AND independientes; basta que una falle para que la tendencia no
se reporte, y las tres están implementadas en `evaluate_indicator()` de
`app/ml/personal_baseline.py`.

---

## 6. Calibración elegida

**Favorecer detección.** Sin médico a bordo y con hasta 20 minutos de retraso
hacia la Tierra, perder una emergencia real cuesta más que una falsa alarma. La
decisión está explícita en `app/services/emergency_service.py` (`CALIBRACION`)
para que sea discutible y no implícita.

Contrapeso: como la cuenta regresiva ejecuta acciones graves sola, las falsas
alarmas tienen costo operativo real (soltar oxígeno de emergencia, mandar a la
tripulación al refugio). Por eso la señal 2 se mantiene específica y la guarda
del rango clínico evita rojos por cambios irrelevantes.

---

## 7. Los dos modos: pasivo y activo

El brief del reto (video de presentación, Rodrigo Leonardi) pide explícitamente
que la herramienta no asuma que el astronauta es médico: debe explicar cómo
medir, por qué importa, qué hacer ante un valor anormal, y adaptarse a
distintos entornos. Esto se tradujo en dos modos, documentados aquí porque
ninguno usa un modelo generativo ni inventa indicaciones médicas:

**Modo pasivo** (`monitoring_service.ingest_reading` → `emergency_service` →
`interlock_service`): cada lectura nueva reevalúa los hazards activos del
tripulante con el detector de la sección 4; si el peor nivel llega a RED, el
estado de la nave pasa de NORMAL a RESTRICTED/LOCKED (`ship_state_event`,
tabla append-only) y las actividades cuyo `min_allowed_state` lo exige quedan
bloqueadas (`ship.activities_with_status`), hasta que el estado vuelve a
normalizarse solo. Esto es **software puro** — una máquina de estados que
decide qué mostrar/permitir en la interfaz — y está documentado así a
propósito: no pretende controlar hardware real de la nave.

**Modo activo** (`assistant_service.handle_emergency`, vía
`button_controller`): el astronauta presiona el botón y reporta por voz
(transcrito offline con faster-whisper si está disponible, con reintento en
texto si no) o por texto directamente. El sistema combina tres fuentes —el
léxico de síntomas (`SYMPTOM_LEXICON`, reglas por palabra clave, no un LLM),
el contexto pasivo ya calculado, y las mediciones que faltan— y devuelve
pasos inmediatos, qué medir (con `how_to_measure` / `why_it_matters` tomados
del catálogo) y una acción (`SELF_RESOLVE` / `NOTIFY_CREW` / `CONTACT_EARTH`).
La acción final es siempre la **más severa** entre lo que ya detectó el modo
pasivo y el piso mínimo de cada síntoma reportado (`min_action`), para que un
síntoma grave nunca quede sin respuesta aunque el sistema pasivo no lo haya
visto todavía, y viceversa.

### Adaptación por entorno

El video pide adaptar la guía según el entorno (nave en tránsito, estación,
base en superficie lunar). No inventamos fisiología distinta por entorno —
eso sería sobre-afirmar—; lo que sí cambia de forma verificable y se
implementó en `ENVIRONMENT_PROFILES` (`app/services/assistant_service.py`)
es:

- **Retraso de comunicación con la Tierra.** En LEO es de segundos (pedir
  ayuda en vivo tiene sentido); en tránsito a Marte o espacio profundo puede
  llegar a ~20 minutos por tramo. El mensaje de la acción `CONTACT_EARTH`
  cambia en consecuencia: en Marte explícitamente dice que no hay que esperar
  respuesta antes de actuar.
- **Nivel de gravedad.** En microgravedad (LEO, tránsito, espacio profundo)
  el paso "recuéstala de lado" no tiene sentido físico — la persona flota —
  y se sustituye por una instrucción de sujeción/restricción. En gravedad
  parcial (Luna, Marte superficie) el paso original se mantiene.

Verificado con una prueba dedicada
(`tests/test_assistant_environment.py`): el mismo reporte de voz ("se
desmayó, no responde") produce pasos y mensaje distintos en `MARS_TRANSIT`
que en `LUNAR_SURFACE`, y el caso sin destino especificado cae explícitamente
a LEO en vez de fallar o adivinar.

Esto sigue siendo superficial frente a lo que un sistema de producción real
necesitaría (protocolos médicos específicos por hábitat, recursos distintos
instalados en cada tipo de base); está marcado como el principal punto de
expansión futura en el `README.md`.

---

## 8. Datos excluidos a propósito

| Dataset | Motivo |
|---|---|
| **DSO 484 (STS-46)**, astronautas reales | Tiene decimales perdidos en el archivo de origen: celdas guardadas como entero (`169` donde por coherencia debería ser `16.9`, `133`→`13.3`, `142`→`14.2`, y más). La relación `antes + desfase = después` **no se cumple ni en las filas limpias**, así que no hay forma de validar una corrección. Se **cita** como respaldo científico (estudio publicado en *Journal of Pineal Research*) pero **no** se usa como insumo del modelo. |
| **MR001G — renina plasmática** | El archivo exportado trae solo metadatos; le falta la columna de valores. |

---

## 9. Qué NO afirma este sistema

Para que nadie lo sobrevenda:

- **No diagnostica.** Entrega una instrucción de acción, no un diagnóstico médico.
- **No está validado para predecir emergencias.** Ningún dato disponible
  contiene emergencias médicas reales en vuelo, así que no hay con qué medir eso.
- **No generaliza desde 3 sujetos.** La señal de sueño es real y significativa en
  los 3, pero 3 sujetos no son una población.
- **Las variables ambientales son simuladas.** CO₂, radiación, presión y
  distancia vienen de escenarios sintéticos marcados como tal en la base de
  datos (`data_origin = 'SIMULATED'`); los umbrales son de demostración, no
  límites médicos ni operacionales.
- **SpO2, temperatura y pulso no tienen fuente real** en los datos disponibles.
- **Los sujetos no son astronautas en vuelo**, excepto los del DSO 484, que está
  excluido del modelo. Los estudios de reposo son análogos terrestres.
- **La adaptación por entorno es operativa, no médica.** Lo que cambia entre
  LEO, órbita lunar, tránsito a Marte y superficie es el retraso de
  comunicación con la Tierra y la instrucción de sujeción en microgravedad —
  no hay protocolos clínicos distintos por entorno todavía; eso requeriría
  guías médicas específicas por hábitat que no están en el alcance de esta
  entrega.
- **El léxico de síntomas (modo activo) es un conjunto de reglas por palabra
  clave, no comprensión de lenguaje natural.** Reconoce patrones de texto en
  español explícitamente escritos; una forma de decir lo mismo que no esté en
  el patrón puede no detectarse, y por eso el modo activo siempre se combina
  con el contexto pasivo en vez de depender solo de lo que el astronauta dice.

El IsolationForest de `app/ml/anomaly_detector.py` se conserva para el caso
multivariado y como vía de expansión cuando exista telemetría real por
tripulante, pero **no es la vía por defecto**, precisamente por lo medido en la
sección 3.
