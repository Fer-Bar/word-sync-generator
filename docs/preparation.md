# Preparación y letras

[Volver al README](../README.md)

## Elegir la referencia

La preparación separa voces e instrumental con Demucs y genera letras con tiempos por palabra.
El texto sigue este orden de prioridad:

1. TXT explícito mediante `--lyrics-text`.
2. LRCLIB, con selección automática o `--lrclib-id`.
3. Genius si no hay una referencia utilizable de LRCLIB.
4. Whisper cuando no hay referencia o se utiliza `--no-lrclib`.

```bash
uv run karaoke ./cancion.flac --title "Mi canción" --artist "Artista" \
  --language es --lyrics-text ./letra.txt
uv run karaoke "YOUTUBE_URL" --lrclib-id 123456
uv run karaoke ./cancion.flac --language es --no-lrclib
```

`--no-lrclib` desactiva todas las referencias externas y la reparación posterior;
no puede combinarse con `--lyrics-text`, `--genius-url` ni `--lrclib-id`.
Un TXT explícito tiene prioridad sobre un ID de LRCLIB o una URL de Genius.
`--genius-url` selecciona una página cuya identidad debe coincidir con los metadatos.

La búsqueda contrasta título, artista, duración y edición. Usa `--title`, `--artist` y
`--album` para corregir metadatos ambiguos. Las decisiones y fallos quedan registrados en
consola y en `lyrics_reference.json`. Genius puede fallar por bloqueos o cambios de su página.

## Alineación y revisión

CTC alinea la referencia con el audio. Si falla, se intenta recuperar tiempos mediante
coincidencias inequívocas con Whisper. El último respaldo conserva el texto de referencia
y estima los intervalos restantes: no equivale a una alineación acústica.

`alignment.json` registra la estrategia y los índices de palabras estimadas en
`grouping.estimated_word_indexes`. `lyrics_validation.json` guarda discrepancias y marcas
informativas de revisión.
`transcription.json`, cuando está disponible,
conserva la transcripción independiente de Whisper.

Los tiempos generados se comprueban contra la energía de las voces para evitar que una palabra
se extienda sobre una pausa larga. Esa comprobación no identifica cantantes y puede confundirse
con filtraciones del instrumental o voces simultáneas. Los tiempos explícitos importados se conservan.

Con `--language auto`, si los metadatos no proporcionan idioma, se usa Whisper porque CTC
necesita un idioma explícito. Sin referencia, los saltos de línea se estiman por longitud,
pausas y puntuación; pueden no coincidir con los versos originales.

## Formato editable

El render consume `lyrics.lyricsfile.yaml`, versión `1.0`, con metadatos, líneas y palabras.
Las líneas cantadas necesitan tiempos por palabra, duraciones positivas y orden temporal
por canal vocal. La confianza debe estar entre `0` y `1`. Se permiten solapamientos entre
cantantes y entre voz principal y voces de fondo; las pausas explícitas se conservan.
Un `end_ms` omitido solo puede inferirse si existe un límite inequívoco posterior.

Edita `lines` y sus palabras: `plain` se deriva de ellas y cambiarlo solo no corrige las letras.
Al usar LyricsEditor, carga las voces y el YAML, revisa y exporta **LyricsFile YAML**.
El render no vuelve a alinear ni transcribir.

Los encabezados como `[Verse 1: Artista]` no se cantan y asignan `agent` a los versos siguientes.
Un encabezado sin cantante borra esa asignación. Varios nombres indican una sección compartida,
no quién canta cada palabra. Los paréntesis se conservan para voces de fondo y los datos
`agent` / `isBackground` explícitos se respetan; esto no es diarización automática.

`reference.txt` conserva el texto de referencia; cuando se dispone del original, incluye sus
encabezados. Tras descargar el trabajo, la recuperación local puede aplicar esa referencia o
buscar Genius si falta y solo hay agrupación heurística. No reemplaza una selección explícita
por otra referencia. La escritura usa respaldo temporal para revertir fallos, no un historial.

## Opciones de preparación

| Option | Default | Purpose |
|---|---:|---|
| `--language` | `en` | Whisper language code; CTC accepts common two-letter codes or ISO 639-3. |
| `--title` | source metadata | Track title override for LRCLIB. |
| `--artist` | source metadata | Artist override for LRCLIB. |
| `--album` | source metadata | Album override for LRCLIB. |
| `--lrclib-id` | automatic | Force one LRCLIB record. |
| `--lyrics-text` | none | UTF-8 TXT with authored verse boundaries; uploaded to Colab. |
| `--genius-url` | automatic search | Select a metadata-checked Genius song when LRCLIB is unavailable. |
| `--no-lrclib` | disabled | Skip lyrics lookup and use Faster Whisper. |
| `--whisper-model` | `large-v3` | Faster Whisper fallback model. |
| `--demucs-model` | `htdemucs_ft` | Source separation model; `htdemucs` is faster. |
| `--visual-style` | `plus` | Shared Switzer typography; karaoke scroll and fixed lyrics pages. |
| `--background-style` | `fluid` | Choose `fluid` or `cosmic-sand`; omit when selecting a static background. |
| `--cover` | none | Extract a procedural palette from local artwork. |
| `--background-image` | none | Local image; no dimming by default. |
| `--background-color` | none | Solid background color; ignored when an image is supplied. |
| `--resolution` | `1080p` | Resolution stored in the prepared job. |
| `--logo`, `--watermark` | repository banner if present | Local image file to overlay as a watermark or logo. |
| `--no-logo`, `--no-watermark` | disabled | Persistently disable the watermark for this job. |
| `--logo-position` | `top_left` | Corner placement (`top_left`, `top_right`, `bottom_left`, `bottom_right`). |
| `--logo-scale` | `0.18` | Logo width relative to video width (maintains aspect ratio). |
| `--logo-opacity` | `0.85` | Watermark opacity from 0.0 to 1.0. |
| `--gpu` | `T4` | Colab GPU variant, subject to account availability. |
| `--auth` | `oauth2` | Colab CLI authentication; `adc` is also supported. |
| `--timeout` | `14400` | Remote timeout in seconds. |
| `--no-cookies` | disabled | Do not upload the local cookies file. |

Consulta `uv run karaoke --help` para la lista completa. La preparación termina antes del
render para permitir revisar el resultado; la revisión externa no es un requisito técnico.

## Modelo de alineación

La configuración utiliza `ctc-forced-aligner` y
`MahmoudAshraf/mms-300m-1130-forced-aligner`, con licencia CC-BY-NC-4.0.
Las dependencias remotas se definen en [colab/requirements.txt](../colab/requirements.txt).
