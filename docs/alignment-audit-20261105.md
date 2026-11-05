# Desfase local aceptado por los controles de alineación

[Volver al README](../README.md)

El experimento posterior de recuperación por tramos se revirtió en `f8511d3` tras
regresiones observadas por el usuario. La alineación actual conserva la lógica de la
copia del 4 de noviembre anterior a la corrida de Jessie: la comparación estructural
solo encuentra cambios en adquisición de audio y la eliminación de un alias sin uso.
Esta auditoría documenta un problema conocido; no implica que esté corregido.

Auditoría del 5 de noviembre de 2026 sobre `outputs/karaoke-20261105-025441-9c8408`,
FOR SIXXX IN THE MORNIN, de Jessie Reyez. **El fallo reproducido está en la aceptación
del alineamiento:** CTC asigna tiempos incorrectos a varias palabras y los controles
permiten entregar ese resultado. Los tiempos ya están mal antes del render.

Esta auditoría no modifica el algoritmo ni el trabajo original. No se ejecutó nueva
inferencia acústica. Distingue el defecto demostrado de las hipótesis que necesitan
experimentos antes de implementar una corrección general.

## Qué sucede entre los segundos 24 y 44

Los números de línea de este documento empiezan en 1. La referencia temporal es el
registro [LRCLIB 39489504](https://lrclib.net/api/get/39489504), consultado durante la
auditoría; son tiempos por frase, no anotaciones manuales por palabra.

| Línea | Inicio LRCLIB | Inicio generado | Diferencia | Fin generado |
| --- | ---: | ---: | ---: | ---: |
| 6 | 21,520 s | 21,540 s | +0,020 s | 23,660 s |
| 7 | 23,820 s | 24,360 s | +0,540 s | 30,600 s |
| 8 | 26,380 s | 30,620 s | **+4,240 s** | 31,460 s |
| 9 | 28,080 s | 31,480 s | **+3,400 s** | 34,240 s |
| 10 | 34,900 s | 35,080 s | +0,180 s | 39,740 s |
| 11 | 38,900 s | 39,780 s | +0,880 s | 41,480 s |
| 12 | 41,660 s | 41,740 s | +0,080 s | 43,700 s |
| 13 | 44,030 s | 44,040 s | +0,010 s | 47,800 s |

La línea 7 ocupa 6,24 segundos y termina 4,22 segundos después del inicio de referencia
de la siguiente. Dentro de esa línea, la tercera palabra empieza en 28,32 s y la última
en 30,54 s. Las dos frases siguientes quedan desplazadas y comprimidas. El inicio de la
línea 10 vuelve cerca de la referencia, pero su última palabra ocupa 38,98–39,74 s;
Whisper sitúa esa frase en 34,70–36,44 s. Esa distribución interna también merece revisión.

El contraste visual con el [video oficial](https://www.youtube.com/watch?v=ua79EB4-CVA)
corrobora el problema, independientemente del LRC:

| Fotograma | Frase del video oficial | Frase del render lyrics |
| --- | --- | --- |
| 24,5 s | Línea 7 | Línea 7 |
| 27 s | Línea 8 | Todavía línea 7 |
| 30 s | Línea 9 | Todavía línea 7 |
| 42 s | Línea 12 | Línea 12 |

Estos fotogramas verifican la frase mostrada, no cada frontera fonética. El tramo
se deforma y después vuelve a coincidir; no corresponde aplicar un offset constante.
La mediana absoluta de desviación frente al LRC es solo 90 ms: una métrica global
puede parecer excelente y ocultar este fallo local.

También aparecen diferencias de inicio en las líneas 15 (-2,62 s), 36 (-3,37 s),
40 (-5,24 s) y 69 (+3,99 s). Son candidatos a revisión; no se han confirmado acústicamente
como errores mediante anotación manual.

## Por qué se acepta el resultado incorrecto

La estrategia guardada es `global_ctc`, con el modelo
`MahmoudAshraf/mms-300m-1130-forced-aligner`, revisión
`49402e9577b1158620820667c218cd494cc44486`. El flujo observable es:

1. `_align_known_lyrics`, en [karaoke_job.py](../colab/karaoke_job.py), alinea el texto
   completo sobre la canción. En ese primer intento los timestamps LRC no restringen
   cada frase: se usan después para comprobar el candidato.
2. `_is_alignment_healthy` acepta el candidato guardado. Sus límites son >30 s de
   discrepancia, >12 s con puntuación media <0,20, o >15 s en dos líneas. Los errores
   de +4,24 y +3,40 s pasan esos controles.
3. La comprobación de compresión extrema tampoco los detecta. Requiere <50 ms/palabra
   y puntuación <0,05, o dos líneas consecutivas con <85 ms/palabra y puntuación <0,15.
   Las líneas 8 y 9 promedian 168 y 251 ms/palabra, con puntuaciones 0,092 y 0,108.
   El algoritmo no detecta aquí una frase estirada que invade las siguientes.
4. Whisper no aporta palabras entre **17,74 y 34,70 s**. La comparación textual deja
   sin anclas aceptadas las líneas 5–12. La última ancla anterior termina en 14,86 s;
   la siguiente comienza en 45,11 s, dentro de la línea 13.
5. `alignment_anchor_check`, en [lyric_references.py](../src/karaoke_app/lyric_references.py),
   verifica 36 fragmentos repartidos en 31 de las 74 líneas. Devuelve `checked` si
   encuentra al menos dos y no detecta desviación grave. No exige cobertura del tramo
   problemático. Además, calcula la discrepancia solo en el inicio del fragmento,
   aunque registre también su final; no verifica todas las palabras interiores.
6. `_verify_alignment_anchors` activa recuperación solo ante `status="drift"`.
   La ausencia de evidencia en una región no activa esa recuperación.
7. `needs_review=true` sí queda guardado; 66 de 74 líneas tienen esa marca. Sin embargo,
   la advertencia es informativa y `render` solo comprueba que el YAML sea válido.
   Por tanto, ambos MP4 pueden generarse con los tiempos defectuosos.

La reproducción local devuelve exactamente:

```json
{
  "healthy_gate_result": true,
  "anchor_gate_result": {
    "status": "checked",
    "checked": 36,
    "severe_deviations": []
  },
  "macro_section_line_counts": [74]
}
```

`checked` describe las anclas comprobadas; no demuestra sincronización correcta de
toda la canción. Las puntuaciones CTC se obtienen de `exp(score)` y no constituyen
probabilidades calibradas de que una palabra esté bien sincronizada.

## Otro defecto en la recuperación

`_parse_synced_lyrics` utiliza el siguiente timestamp LRC como final de la línea.
`_group_lines_into_macro_sections` intenta detectar pausas calculando
`siguiente.inicio - actual.fin`. Para este LRC, ese valor es cero en todas las transiciones:
la reproducción produce **una sola sección de 74 líneas**.

Ese final es una frontera de presentación estimada, no el final acústico del canto.
Usarlo para detectar silencios impide segmentar este caso. Si solo se endureciera el
primer control, el respaldo podría volver a alinear prácticamente toda la canción.
La ruta no se ejecutó en el trabajo auditado, porque se aceptó el candidato global;
es un defecto adicional que debe resolverse antes de confiar en la recuperación.

## Qué queda descartado y qué sigue sin demostrarse

- **Reparación textual posterior:** `alignment.json` registra 597 palabras reutilizadas,
  cero estimadas y `word_timings_preserved=true`. El control de colas vocales solo recortó
  la última palabra de la canción. Ninguna de esas operaciones creó el desfase de 24–44 s.
- **Corrimiento del audio en el render:** la correlación de PCM mono a 8 kHz en ventanas
  0–20, 20–44, 44–65 y 100–120 s arroja lag 0 ms para karaoke frente al instrumental
  y +7 ms para lyrics frente al original. Las correlaciones compensadas superan 0,998.
  No explican desplazamientos de varios segundos. La intro estaba desactivada.
- **Conversión de tiempos:** el SRT de preparación coincide con el del render lyrics;
  `build_browser_scene` conserva los timestamps al convertir segundos a milisegundos,
  y los offsets del reproductor están en cero.
- **Audio vacío en el tramo omitido por Whisper:** el stem contiene señal apreciable
  entre 21 y 34 s, con RMS de aproximadamente -13 a -15 dBFS. Eso descarta silencio
  digital, pero no garantiza inteligibilidad ni ausencia de filtración instrumental.
- **VAD como causa demostrada:** la transcripción usa `vad_filter=True`, umbral 0,25,
  pausa mínima 500 ms y padding 250 ms. No se guardaron las regiones VAD ni las emisiones
  CTC. Falta comparar reconocimiento con/sin VAD y voces frente a mezcla para atribuir
  la omisión al detector, al reconocedor o a la separación.

El bug de aceptación está demostrado. **La causa acústica exacta por la que el modelo
eligió esa trayectoria temporal no está demostrada.** No corresponde culpar exclusivamente
a Demucs, al texto LRC o al VAD sin esa comparación.

Los textos normalizados de las 74 líneas de LRCLIB coinciden con la salida. La corrida
no conservó una instantánea de los tiempos LRC originales: esta auditoría usa una consulta
posterior del mismo día. Se guardó su hash y sus timestamps. Esa limitación de trazabilidad
impide afirmar que el proveedor nunca cambió las marcas; el contraste visual aporta
evidencia adicional para las frases afectadas.

## Corrección general y criterios de aceptación

No basta bajar un umbral ni trasladar toda la canción. Una corrección debe:

1. Separar calidad textual, cobertura temporal y precisión por palabra. Informar
   intervalos sin verificación en vez de resumirlos como éxito por tener anclas en otra zona.
2. Identificar regiones sospechosas combinando referencia compatible, desplazamiento de
   frases vecinas, puntuaciones débiles, duración y cobertura ASR. Ninguna señal aislada
   debe imponer timestamps nuevos. Conservar la protección contra estribillos ambiguos.
3. Reintentar bloques acotados por evidencia independiente y con contexto; distinguir
   límites LRC estimados de finales acústicos. Preservar las regiones sustentadas fuera
   del bloque. Comparar con/sin VAD y mezcla/voces donde falte reconocimiento.
4. Evaluar el candidato por inicios, finales y palabras interiores. Exigir texto íntegro,
   orden válido por voz y ausencia de deterioro fuera de la región. Si persiste un conflicto
   temporal grave, informar los segundos pendientes y no declararlo listo automáticamente.
5. Guardar la referencia temporal original, versiones, cobertura y decisiones por candidato.
   Una advertencia textual ordinaria no debe confundirse con un fallo temporal grave.

Cambiar todas las canciones por confianza baja o por `needs_review` causaría falsos positivos:
9 de 15 trabajos inspeccionados conservan `needs_review=true`; los otros 6 no guardan el campo.
La inspección no certifica esos trabajos. Tampoco es seguro sustituir todo por Whisper
(omitió el tramo), imponer siempre el LRC (puede ser otra edición), desactivar VAD globalmente
o repartir palabras uniformemente como si fueran tiempos acústicos.

La validación antes de modificar producción debe cubrir:

| Caso | Qué debe proteger |
| --- | --- |
| Este tramo sin ASR, con frases estiradas y comprimidas | Detectar el conflicto aunque no alcance 12 s |
| Inicio de frase correcto, palabras interiores incorrectas | Evaluar más que el primer timestamp |
| LRC con offset o edición distinta | Evitar forzar una referencia equivocada |
| Rap rápido y notas sostenidas correctas | Evitar rechazar por duración aislada |
| Estribillos repetidos, coros y múltiples voces | Conservar ambigüedad y solapamientos válidos |
| LRC con finales inferidos del siguiente inicio | No confundirlos con límites de silencio |
| Sin referencia, proveedor caído o YAML corregido por usuario | Conservar las rutas existentes y tiempos explícitos |
| Recuperación local que empeora otra región | Rechazar la regresión aunque mejore el promedio |

El corpus local registra `he-belongs`, `ghost` y `solar-eclipse` como referencias de
texto y palabras confirmadas por el usuario. Son casos de desarrollo, no una muestra
independiente. Se necesita nueva inferencia comparada con ellos y con anotación manual
de esta canción, además de casos reservados para comprobar generalización. Medir máximos,
percentiles y ventanas, separando voz principal y coros; no basta una media global.

## Reproducción y límites de las pruebas

Desde la raíz del repositorio:

```bash
source .venv/bin/activate
uv run python reports/reyez-alignment-audit-20261105/replay.py
```

El script local comprueba los hashes de los cinco artefactos auditados, reconstruye
los tiempos de referencia congelados y ejecuta los controles actuales. No descarga,
no carga modelos y no modifica las entradas. Los archivos privados de evidencia y
el script están en `reports/reyez-alignment-audit-20261105/`, excluidos de Git;
el comando requiere conservar esa carpeta y el trabajo original.

La comprobación de la suite existente fue:

```bash
uv run pytest tests/test_karaoke_job.py tests/test_asr_alignment_recovery.py \
  tests/test_vocal_boundaries.py tests/test_reference_vocals.py -q
```

Resultado: **101 pruebas pasaron**. Al mismo tiempo, el caso real reproduce el falso
negativo. Es una laguna de cobertura: esas pruebas no certifican precisión acústica
ni una corrección que todavía no se ha implementado. Los artefactos originales
conservaron sus hashes durante la auditoría.
