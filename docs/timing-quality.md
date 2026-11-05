# Comprobación y recuperación de la sincronización

[Volver al README](../README.md)

La preparación evalúa conflictos temporales por región después del alineamiento global.
Combina palabras reconocidas de forma independiente, discrepancias locales con una
referencia temporal consistente y puntuaciones acústicas débiles. Una nota sostenida,
una puntuación baja o la falta de transcripción no bastan por sí solas para cambiar tiempos.

Cuando existe un conflicto, intenta realinear un tramo de hasta 30 segundos, añadiendo
contexto en sus bordes. Solo sustituye las líneas marcadas: las líneas vecinas sirven de contexto y
conservan sus tiempos. Si falta reconocimiento, prueba ese intervalo sin VAD sobre las
voces y, cuando está disponible y hace falta, sobre la mezcla original. La configuración
general de Whisper permanece igual.

Un candidato debe resolver los conflictos detectados y mejorar el acuerdo con palabras
independientes o aportar una mejora acústica acompañada por una referencia consistente.
Se rechaza si empeora las anclas independientes o rompe la estructura temporal.
La puntuación acústica no es una probabilidad calibrada de sincronización correcta.

La recuperación por secciones también limita el tamaño de los bloques cuando los finales
LRC coinciden con el siguiente inicio. No interpreta esas fronteras como prueba de silencio.

## Qué guarda cada trabajo

| Archivo | Contenido |
| --- | --- |
| `timing_reference.json` | Referencia original con sus tiempos, anterior al alineamiento. |
| `timing_quality.json` | Conflictos, cobertura por palabra y huella del resultado evaluado. |
| `timing_recovery.json` | Ventanas reintentadas y decisiones sobre los candidatos. |
| `timing_recovery_transcription.json` | Evidencia de reconocimiento utilizada por la recuperación. |

Los diagnósticos también aparecen en `alignment.json` y `lyrics_validation.json`.
`transcription.json` conserva la transcripción inicial. Los tiempos por palabra explícitos
de una referencia se conservan y no pasan por esta reparación automática.

Los estados distinguen `checked`, `partial`, `unverified` y `conflict`. Una comprobación
parcial informa su cobertura; no certifica las palabras que carecen de evidencia.
Estas comprobaciones detectan clases concretas de errores, no garantizan precisión perfecta.

## Revisar un conflicto pendiente

La preparación conserva los artefactos aunque la recuperación no resuelva el conflicto.
El render final indica los intervalos pendientes y se detiene antes de crear una sesión GPU.
Las advertencias textuales ordinarias y la cobertura parcial no bloquean el render.

Revisa el audio y los tiempos en el editor o genera una vista previa local:

```bash
uv run karaoke preview outputs/JOB_ID --mode lyrics --start 20 --duration 25 \
  --output outputs/previews/revision.mp4
```

Después de revisar y, cuando corresponda, corregir los tiempos:

```bash
uv run karaoke render outputs/JOB_ID --mode both --accept-timing-review
```

La opción confirma la revisión de esa ejecución; no repara ni altera los timestamps.
Editar un YAML no borra silenciosamente un conflicto anterior: su huella permite advertir
que el diagnóstico corresponde a una versión previa. Los trabajos antiguos sin este
diagnóstico conservan su comportamiento anterior.
