# GUARDIÁN — Validación del modelo

Este documento reporta lo que el sistema **sí** y **no** puede demostrar con los
datos disponibles. Está escrito para que cualquiera pueda reproducir los números
y para que nadie tenga que confiar en nuestra palabra.

Reproducir todo:
```bash
cd backend
python -m data.seed.seed_catalog
python -m data.seed.seed_real_data
python -m data.seed.seed_nasa_analog
python -m tests.test_personal_baseline
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

## 7. Datos excluidos a propósito

| Dataset | Motivo |
|---|---|
| **DSO 484 (STS-46)**, astronautas reales | Tiene decimales perdidos en el archivo de origen: celdas guardadas como entero (`169` donde por coherencia debería ser `16.9`, `133`→`13.3`, `142`→`14.2`, y más). La relación `antes + desfase = después` **no se cumple ni en las filas limpias**, así que no hay forma de validar una corrección. Se **cita** como respaldo científico (estudio publicado en *Journal of Pineal Research*) pero **no** se usa como insumo del modelo. |
| **MR001G — renina plasmática** | El archivo exportado trae solo metadatos; le falta la columna de valores. |

---

## 8. Qué NO afirma este sistema

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

El IsolationForest de `app/ml/anomaly_detector.py` se conserva para el caso
multivariado y como vía de expansión cuando exista telemetría real por
tripulante, pero **no es la vía por defecto**, precisamente por lo medido en la
sección 3.
