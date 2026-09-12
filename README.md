# Colab Karaoke Video Generator

Prepare reusable audio stems and word-timed LyricsFile YAML on Colab, correct the result in the external
[LyricsEditor](https://dotslashgabut.github.io/lyricseditor/), then render ASS and video without repeating media
acquisition, source separation, alignment, or transcription.

## Quick path

```bash
uv sync --dev
uv run karaoke SOURCE --language en
# (Opcional) Ajustar estilos, fuentes y previsualizar en vivo:
uv run karaoke editor outputs/JOB_ID
# Corregir letras si es necesario en LyricsEditor:
# outputs/JOB_ID/lyrics.lyricsfile.yaml
# Renderizar video final en Colab:
uv run karaoke render outputs/JOB_ID
```

The preparation command finishes after downloading `outputs/JOB_ID`; no process remains paused. Open
[LyricsEditor](https://dotslashgabut.github.io/lyricseditor/) separately and:

1. Load `vocals.flac` as the audio file.
2. Load `lyrics.lyricsfile.yaml` as the lyrics file.
3. Review low-confidence words with `Alt+N` and `Alt+P`.
4. Export **LyricsFile YAML**.
5. Replace the job's `lyrics.lyricsfile.yaml` with the exported file.

## Live Style Editor & Preview

Customize typography, colors, outline, shadow, margins, and background overlay with instant zero-dependency live preview before rendering:

```bash
uv run karaoke editor outputs/JOB_ID
```

- **Live synchronized Canvas preview**: Plays local audio (`instrumental.flac` or `vocals.flac`) and animates the karaoke text wipe in real time at 60 FPS.
- **Typography & Styling**: Choose from popular web fonts or system fonts, adjust font size, line spacing, primary color, karaoke highlight color, outline width/color, and shadow depth/opacity.
- **Background Dimming**: Adjust overlay darkness slider for background images.
- **Instant Persistence**: Updates `job.json` and regenerates `.ass` subtitle files immediately.
- **Snapshot Export**: Download full-resolution PNG frames for visual QA.

## Estilos predeterminados: karaoke scroll y lyrics fijo

Los trabajos nuevos guardan **Plus** en `job.json`: **Switzer Semibold**, blanco/gris,
barrido por palabra y el mismo ancho y espaciado en ambos modos.
**Karaoke** desplaza las frases y muestra contexto atenuado; **lyrics** presenta páginas
fijas sin scroll. Las líneas se centran horizontalmente, incluso cuando una página larga
se reduce para caber. El render conserva la marca de agua configurada y termina la intro
antes de mostrar las letras; no hace falta cambiar `job.json` para aplicar el centrado.
Los MP4 usan **Braccato 1.6.2**, el motor de animaciones de Better Lyrics,
capturado en Chromium a los tiempos exactos de cada fotograma: barrido con borde suave,
brillo que se desvanece y un pequeño movimiento horizontal por palabra. La animación no
recalcula el espaciado de las palabras vecinas. Se conserva el mismo motor para la vista
previa y el render de Colab. Las líneas anteriores se atenúan al 33 % con desenfoque y las
siguientes al 66 %, siguiendo el CSS de Even Better Lyrics compartido como referencia.

Para generar vistas previas locales, instala Chromium una vez:

```bash
uv run playwright install --with-deps chromium
```

Colab instala Chromium automáticamente y recibe el motor, la fuente y los tiempos dentro
del paquete de render. La captura fotograma a fotograma añade tiempo al render y utiliza
un video transparente temporal. Los archivos ASS se siguen exportando como alternativa
compatible, pero su animación aproximada no reproduce todos los efectos del MP4.
El motor original se incluye bajo licencia MIT en `src/karaoke_app/assets/braccato/`, con
su versión y procedencia en `PROVENANCE.json`; la fuente conserva su licencia independiente.

```bash
# Nuevo trabajo: Plus y fondo fluido por defecto.
uv run karaoke SOURCE --language en

# Elegir arena cósmica al preparar el trabajo:
uv run karaoke SOURCE --background-style cosmic-sand

# Fondo fluido con los colores de una portada local:
uv run karaoke SOURCE --background-style fluid --cover portada.jpg

# Renderizar ambos modos con las preferencias guardadas:
uv run karaoke render outputs/JOB_ID --mode both
```

La tipografía y el fondo son independientes: `--visual-style plus|classic` elige las letras;
`--background-style fluid|cosmic-sand` elige el fondo. `cosmic-sand` usa el generador granular
cósmico y `fluid` usa gradientes suaves en movimiento. `--cover` toma dos colores dominantes
de una imagen local para cualquiera de los fondos procedurales. Sin portada, los trabajos
nuevos usan la paleta cálida del generador. Las opciones explícitas `--background-image` y
`--background-color` conservan su fondo estático y no se combinan con `--background-style`.

Para **guardar estas preferencias en un trabajo existente**, sin tocar el JSON a mano:

```bash
uv run karaoke configure outputs/JOB_ID --background-style fluid --cover portada.jpg
# O arena cósmica con las mismas letras:
uv run karaoke configure outputs/JOB_ID --background-style cosmic-sand
uv run karaoke render outputs/JOB_ID
```

`configure` aplica Plus por defecto, guarda `job.json` de forma atómica y conserva el archivo
anterior en `backups/`. No modifica audio ni letras. Repetir la misma configuración no crea
respaldos adicionales. Para recuperar la configuración anterior, restaura ese backup.

También puedes cambiar opciones **solo para un render**, conservando el trabajo guardado:

```bash
uv run karaoke render outputs/JOB_ID --visual-style plus --background-style cosmic-sand
uv run karaoke render outputs/JOB_ID --background-style fluid --cover portada.jpg
```

`render` preserva el fondo y el estilo guardados por defecto (`--theme job`). Las paletas
`--theme aurora|sunset|synthwave|stellar|random` siguen disponibles. El alias
`--theme even-better-lyrics-plus` aplica Plus y fondo fluido juntos.

### Muestras locales

```bash
uv run karaoke preview outputs/JOB_ID --mode lyrics --start 15 --duration 8 --output outputs/previews/lyrics.mp4
uv run karaoke preview outputs/JOB_ID --mode karaoke --start 15 --duration 8 --output outputs/previews/karaoke.mp4
```

`preview` usa Plus, respeta el fondo guardado y acepta `--background-style`, `--cover`,
`--height 720` y `--seed N`. Lyrics usa el audio original; karaoke usa el instrumental.
Genera MP4, ASS (con tiempos de la canción completa) y JSON con modo y configuración.
No sobrescribe resultados existentes. La muestra incluye letras y fondo; `render` añade
intro y marca de agua. Para trabajos con fondo estático, indica un `--background-style`
al previsualizar. El editor Canvas antiguo no representa estos movimientos; usa `preview`.

El diseño adapta [Even Better Lyrics Plus, de Noah & BetterLyrics](https://github.com/better-lyrics/themes/tree/master/themes/eblp).
El fondo fluido limita el brillo para proteger la legibilidad y comparte paleta entre video,
intro y miniatura. No detecta beats ni reproduce exactamente el shader Kawarp de
[Better Lyrics Shaders](https://github.com/better-lyrics/shaders).

La primera ejecución del renderizador descarga Switzer Semibold de
[Fontshare](https://www.fontshare.com/fonts/switzer), con su licencia, a `~/.cache/karaoke/fonts/`.
El archivo original se incluye temporalmente en el paquete enviado a Colab y no se distribuye
con el repositorio. Una descarga fallida produce un error en vez de sustituir la fuente.

## Miniaturas e intro automáticas al renderizar

```bash
# Por defecto: configuración guardada y ambos modos.
uv run karaoke render outputs/JOB_ID --mode both
# Elegir tema o elegir uno aleatorio para todos los artefactos del render:
uv run karaoke render outputs/JOB_ID --mode both --theme synthwave
uv run karaoke render outputs/JOB_ID --mode both --theme random
# O solo uno: --mode lyrics / --mode karaoke
```

Cada render genera automáticamente el thumbnail y la intro de cada modo con **el mismo diseño**:
artista arriba, título grande condensado, textura marfil, sombra y etiqueta LYRICS/KARAOKE.
Ambos usan la misma función de dibujo y las mismas fuentes incluidas en el proyecto.
No hace falta ejecutar `thumbnail` ni `intro` antes. Los gráficos se regeneran en cada render;
un `intro_card.png` viejo no se reutiliza.

- **Texto:** toma `title` y `source.artist` de `job.json`; `metadata.artist` sirve de respaldo.
  Puedes sobrescribir ambos con `intro.title` / `intro.artist`. Si falta el artista, muestra solo el
  título y avisa en consola, sin inventar un nombre.
- **Fondo guardado:** `render` conserva el fondo de `job.json` por defecto, incluidos fondos estáticos.
  Los nuevos trabajos usan fondo fluido salvo que elijas otro. Puedes cambiar su tipo con
  `--background-style` y su paleta con `--theme`. El PNG corresponde al instante cero del
  mismo generador, resolución, semilla, colores y opacidad usados por el MP4.
- **Intro instrumental:** superpone un PNG transparente sobre el fondo en movimiento, sin detenerlo
  ni desplazar audio o letras. Por defecto dura hasta 5 segundos, terminando como máximo 0.8 segundos
  antes de la primera voz de cualquier cantante. Si las voces entran inmediatamente, se omite la
  intro para no tapar la letra. La salida se desvanece suavemente.
- **Watermark:** la intro no contiene ningún logo. El render añade una única marca de agua en
  la posición del trabajo (por defecto, arriba a la izquierda), también durante la intro.
  El thumbnail coloca el logo abajo a la izquierda. `--no-logo` desactiva ambas marcas.
  El campo antiguo `intro.logo` ya no se utiliza.

### Temas de fondo

| `--theme` | Estilo | `color` | `secondary_color` | `base_color` |
| --- | --- | --- | --- | --- |
| `synthwave` | Synthwave / Pop nocturno, neón | `#7928CA` | `#00DFD8` | `#080711` |
| `sunset` | Lofi / R&B cálido, atardecer cósmico | `#B83B5E` | `#F9A826` | `#0D0709` |
| `aurora` | Ambient / Dream Pop, aurora boreal | `#1D4E89` | `#52B788` | `#040B0E` |
| `stellar` | Trap / Dark Rock / Metal, monocromático estelar | `#3F3F46` | `#CBD5E1` | `#050506` |

`--theme random` elige un tema y una semilla una sola vez por render, compartidos por lyrics,
karaoke, miniaturas y fondos. La selección se registra en consola y en `render-settings.json`.
Para repetirla, usa el nombre del tema elegido y `--seed N`. El valor de la semilla por defecto
es 7, o el del trabajo si ya era cósmico. Al aplicar una paleta a un trabajo cósmico se conservan
sus controles de movimiento y textura; `--theme job` conserva también sus colores.
Estas opciones no modifican el `job.json` original.

### Logos compartidos y carpetas

Guarda los diseños reutilizables en `logos/` y selecciónalos desde cualquier trabajo:

```bash
uv run karaoke render outputs/JOB_ID --theme sunset --logo logos/banner.png --logo-position top_left
```

Los jobs guardan rutas como `"path": "logos/banner.png"`. Una imagen elegida fuera de `logos/`
se importa allí una sola vez, evitando duplicados por contenido. Al preparar nuevos trabajos
ya no se guarda una copia de la marca de agua en cada carpeta de canción. Durante el render
se incluye temporalmente una copia en el paquete enviado a Colab, necesaria para procesar el video.

```text
logos/                         # Marcas reutilizables: banner.png, thumbnail.png, principal_logo.png
references/                    # Imágenes originales de referencia, no resultados
  thumbnails/
src/karaoke_app/assets/fonts/   # Fuentes y licencias
outputs/
  JOB_ID/                      # Audio, letras, job.json y backups/ de configuración
    renders/FECHA-MODO/         # Videos, thumbnails/, intro/, fondos y render-settings.json
  thumbnails/ARTISTA-TITULO/    # Solo al ejecutar el comando thumbnail independiente sin job
```

### Actualizar trabajos antiguos

```bash
# Ver qué jobs necesitan cambios, sin escribir archivos:
uv run karaoke migrate outputs --dry-run
# Migrar todos los jobs preparados (no recorre renders ni carpetas de recuperación):
uv run karaoke migrate outputs
# Migrar solamente uno:
uv run karaoke migrate outputs/JOB_ID
# Conservar un fondo estático deliberado:
uv run karaoke migrate outputs/JOB_ID --theme job
```

La migración convierte el JSON al formato actual, completa los valores de estilo, sustituye rutas
locales de watermark por referencias a `logos/` y elimina `intro.logo`. En el modo predeterminado
`auto`, los fondos estáticos pasan a aurora y los fondos cósmicos conservan su paleta y controles.
Respeta `intro.enabled: false` y `watermark.enabled: false`, y conserva audio, letras y metadatos.
También acepta `--theme synthwave|sunset|aurora|stellar` para guardar una paleta determinada.

Antes de modificar un job crea `JOB_ID/backups/job-HASH.json` con el contenido anterior y reemplaza
`job.json` de forma atómica. Repetir la migración no cambia un trabajo actualizado ni crea backups
adicionales. Para restaurar la configuración anterior, copia el backup sobre `job.json`; los
archivos de audio, letras y fondos de esos trabajos se conservan. `render --theme job` usa exactamente
el fondo guardado; `render` sin opciones también respeta ahora esa configuración.

Puedes ajustar la duración o desactivar únicamente la intro en `job.json`:

```json
"intro": {
  "enabled": true,
  "duration": 5.0
}
```

`intro.start` permite retrasar la aparición y `intro.end` añade un límite al final; siempre se respeta
la entrada de las voces. `"enabled": false` desactiva la tarjeta, pero conserva los thumbnails.

Junto a los videos descargados en `JOB_DIR/renders/FECHA-MODO/` encontrarás:

| Archivo | Contenido |
| --- | --- |
| `thumbnails/thumbnail_lyrics.png` | Miniatura de lyrics, si se solicitó ese modo. |
| `thumbnails/thumbnail_karaoke.png` | Miniatura de karaoke, si se solicitó ese modo. |
| `intro/intro_lyrics.png`, `intro/intro_karaoke.png` | Capas transparentes usadas por las intros habilitadas. |
| `background.png` | Fondo sin texto en la resolución del video. |
| `background.mp4` | Bucle de fondo animado (por defecto); no se genera con un fondo estático y `--theme job`. |
| `render-settings.json` | Tema elegido y parámetros efectivos de fondo/video para reproducir el render. |

`uv run karaoke intro outputs/JOB_ID` sigue disponible para generar manualmente `intro_card.png`
con el mismo diseño, sin logo (etiqueta LYRICS; acepta `--mode karaoke`) para el editor. La selección de modo y los tiempos descritos
arriba los resuelve automáticamente `render`; el editor aún usa su propia previsualización de tiempos.

Run `uv run karaoke render PATH_TO_JOB` only after the corrected file is in that prepared job folder. It validates the
folder and renders both the instrumental karaoke video and the original-audio lyrics video in one Colab session. Use
`--mode karaoke` or `--mode lyrics` only when one output is needed. Results are downloaded under
`JOB_DIR/renders/<timestamp>-<mode>/`:
- **Karaoke mode**: `{title}_karaoke.mp4` rendered with instrumental audio and synchronized karaoke subtitles with word-by-word highlight wipes and automatic line wrapping.
- **Lyrics mode**: `{title}_lyrics.mp4` rendered with original audio and synchronized subtitles with customizable 2-color progressive fill (`inactive` for unsung words, `active` for words being sung and retaining active highlight throughout the line):
  ```json
  "style": {
    "lyrics_colors": {
      "inactive": "#9A8F8B",
      "active": "#F4EEE6"
    }
  }
  ```

## Lyrics strategy

Preparation selects the first usable source in this order:

1. A matching LRCLIB LyricsFile that already contains word timings.
2. LRCLIB line-synced or plain lyrics aligned to the separated vocal stem with CTC forced alignment.
3. Faster Whisper transcription with word timestamps when LRCLIB has no safe match or alignment fails.

Automatic LRCLIB matches evaluate track title, artist variants, duration, and song editions (such as Acoustic or Live)
through progressive discovery tiers (exact metadata, without album, primary artist, and structured search) while
strictly validating candidates to prevent mismatches. Use `--lrclib-id ID` to select a known record,
or `--no-lrclib` to force Faster Whisper. Local files and noisy video metadata can be corrected with `--title`,
`--artist`, and `--album`.

An explicit LRCLIB ID is fetched before source acquisition; automatic matching runs after acquisition but before
Demucs separation. The selected record is reused during lyric preparation. Conflicting edition tags are rejected
even if they share another tag, such as `Live Acoustic` versus `Live Remix`. Repeated lyric whitespace is normalized
consistently before alignment. Recovery crops preserve explicit sustained/overlapping vocal intervals while treating
LRC ends inferred from the next timestamp as boundaries, not evidence of continuous singing.

The CTC path pins `ctc-forced-aligner` and `MahmoudAshraf/mms-300m-1130-forced-aligner`. The package metadata and
model use **CC-BY-NC-4.0**, so this configuration is for non-commercial use only. Numeric tokens are aligned through
their spoken form and mapped back to the original text, so values such as `9:30` remain one editable LyricsFile word.
CTC leaves a free alignment segment between lyric units so pauses remain timing gaps instead of extending the previous
word.

Parenthesized spans are preserved as background vocals. Generated CTC lyrics use the neutral `v1` agent, add
`isBackground: true` to words inside parentheses, and keep the parentheses in the line text. Existing `agent` and
`isBackground` values from LRCLIB LyricsFile records are preserved; the pipeline does not attempt to identify singers
from plain lyrics.

## Prepared job

| File | Purpose |
|---|---|
| `job.json` | Durable media, source, alignment, video, and background configuration. |
| `lyrics.lyricsfile.yaml` | Canonical editable lyrics and word timings. |
| `vocals.flac` | Separated vocal stem recommended for alignment review. |
| `instrumental.flac` | Reusable accompaniment for karaoke renders. |
| `original_audio.*` | Original source used by lyrics-mode renders. |
| `alignment.json` | Original CTC or Whisper alignment evidence for diagnosis. |
| `background.*` | Copied background image when one was supplied. |

LyricsFile import accepts omitted `end_ms` values when the next word or line provides an unambiguous boundary.
Rendering is stricter: non-empty lines require words, positive durations, ordered timings within each vocal channel,
and confidence values between `0` and `1`. Timings may overlap across agents or between main and background vocals.
Explicit gaps between `end_ms` and the next `start_ms` remain silent in the karaoke effect.

### Background and configuration

New jobs use `schema_version: 2`. Image backgrounds keep their original brightness by default and do not require
a color. The following is a `job.json` section, not a complete job:

```json
"background": {
  "kind": "image",
  "path": "background.png",
  "overlay_opacity": 0
}
```

`overlay_opacity` adds black dimming from `0` (none) to `1` (fully black); it is not a color tint.
For a solid background, use `{"kind": "solid", "color": "#0B1020"}` instead.
`--background-color` is ignored when `--background-image` is supplied. Opacity belongs only in `background`,
not in `style`. Known legacy image colors and solid-background opacities are validated and discarded on normalization.

Existing v1 jobs migrate in memory without rewriting their files. Image jobs preserve their explicit background
opacity, or the historical `0.38` default; the old style-only opacity is discarded because rendering ignored it.
Existing default watermark behavior is preserved for v1 when the repository banner is available. New v2 jobs do not
implicitly add a watermark at render time. `--no-logo` persists `{"enabled": false}` so a later render stays unbranded.
An explicitly configured missing watermark fails instead of silently using another logo.

### Fondo dinámico de polvo cósmico (render y preview por CLI)

Para recrear el estilo de `references/background_for_lyrics.png` con nubes que fluyen y se deforman,
reemplaza la sección `background` de tu `job.json` por la del archivo
[`examples/cosmic-background.json`](examples/cosmic-background.json). El PNG es una referencia visual:
el generador crea una nebulosa procedural con textura de polvo integrada, sin añadir partículas independientes.
No necesita una imagen de entrada ni cambios en el editor.

Configuración mínima:

```json
"background": {
  "kind": "cosmic",
  "color": "#BC737D",
  "secondary_color": "#E5A28E",
  "base_color": "#08090C",
  "overlay_opacity": 0.15,
  "opacity": 0.85,
  "speed": 0.35,
  "turbulence": 0.8,
  "seed": 7,
  "loop_seconds": 20
}
```

Genera primero un MP4 local sin audio, letras ni conexión a Colab:

```bash
# Prueba el ejemplo sin preparar una canción.
uv run karaoke background examples/cosmic-background.json --output outputs/cosmic-preview.mp4

# Usa exactamente el background y la resolución/fps de tu job.json.
uv run karaoke background outputs/mi-job --output outputs/mi-preview.mp4

# Fragmento de 4 segundos desde el segundo 6, a menor resolución.
uv run karaoke background outputs/mi-job/job.json --duration 4 --start 6 \
  --width 640 --height 360 --fps 15 --output outputs/mi-preview-corto.mp4

# Una vez ajustado background en job.json, renderiza como siempre.
uv run karaoke render outputs/mi-job --mode lyrics --theme job
```

El comando acepta un directorio de job, un `job.json`, o un JSON independiente con `background` y
`video` opcional (por defecto 1280×720 a 24 fps). También acepta solo el objeto `background`.
Los overrides de CLI no modifican el archivo de configuración. Usa `--width` y `--height` juntos
con la misma relación de aspecto del render para conservar la composición. Las dimensiones deben ser pares.

| Parámetro dentro de `background` | Default | Efecto / rango |
| --- | --- | --- |
| `color` | `#BC737D` | Color principal del polvo; RGB hexadecimal. |
| `secondary_color` | `#E5A28E` | Color de las zonas iluminadas. |
| `base_color` | `#08090C` | Color del fondo detrás de las nubes. |
| `opacity` | `0.85` | Presencia de las nubes sobre el fondo, 0–1. |
| `overlay_opacity` | `0` | Capa negra sobre todo el fondo, 0–1. Se ve también en el preview. |
| `speed` | `0.35` | Intensidad del desplazamiento por segundo, 0–3; 0 congela el movimiento. |
| `turbulence` | `0.8` | Deformación de las nubes, 0–2. |
| `density` | `0.55` | Cuánto espacio ocupa la nebulosa, 0–1. |
| `detail` | `0.65` | Granularidad del polvo, 0–1; 0 deja velos lisos, 1 acentúa motas y huecos finos. |
| `brightness` | `1` | Brillo de las nubes, 0–3. |
| `contrast` | `1.4` | Separación entre nubes y vacíos, 0.2–3. |
| `scale` | `3` | Escala espacial del ruido, 1–8; valores altos crean formas más pequeñas. |
| `seed` | `7` | Composición reproducible, entero de 0 a 4294967295. |
| `loop_seconds` | `20` | Duración del bucle continuo, 2–120 segundos. |

**`overlay_opacity` oscurece; no cambia el tono.** Para pasar del rosa al azul, cambia `color` y
`secondary_color`. Para bajar la intensidad sin cambiar la paleta, aumenta `overlay_opacity`.
El generador aplica este oscurecimiento una sola vez antes de superponer letras, logo e intro.
Con `overlay_opacity: 1` el fondo será negro tanto en el preview como en el render.

La estética usa velos amplios y translúcidos, con polvo de distintos tamaños que también aparece tenuemente
en los espacios oscuros. `detail` controla ese grano, mientras `density` controla la cobertura de los velos;
aumentar `density` no sustituye al grano. El MP4 del fondo se codifica con ajuste `grain` para conservar la
textura fina. Es una recreación procedural del estilo de la referencia, no una reproducción de su composición.

Preview y Colab usan el mismo generador y la misma semilla. Colab genera un bucle una sola vez por ejecución
y lo repite para cubrir la canción, reutilizándolo si renderizas ambos modos. El bucle cierra sin un corte de
movimiento; un preview recortado con `--duration` no necesariamente cierra. Puede haber pequeñas diferencias
de compresión entre el preview y el video final. La generación usa CPU (NumPy y Pillow) y el preview incluye
un FFmpeg portátil mediante `imageio-ffmpeg` cuando no hay uno instalado. Generar el bucle puede tardar varios
minutos; para probar parámetros usa primero fragmentos cortos. Esta funcionalidad se configura por JSON y CLI;
el editor de estilos no previsualiza la nebulosa.

Configuration rejects unknown keys, invalid booleans, non-finite numbers, and out-of-range values with field-specific
errors. `source`, `alignment`, `preparation`, and optional `metadata` remain extensible provenance objects.
`preparation` records requested language and separation/transcription models; `alignment` records the effective
language, strategy, and fallback reason when applicable.

### Preparation failures

SOURCE validates local background/logo images and option ranges before provisioning. After remote execution it
attempts to retrieve status even if execution failed. Status/archive downloads have three attempts, each bounded
to 300 seconds. Results are validated and extracted in staging before the final job directory is published.

On failure, inspect `outputs/JOB_ID.recovery/recovery.json` (or the selected output directory). It records the
session, remote artifact paths, errors, downloaded files, and whether session shutdown was confirmed. A downloaded
`result.zip` survives failed extraction; a lyrics-stage failure can additionally provide `checkpoint.zip` containing
the original audio, separated FLAC stems, and `checkpoint.json` diagnostics.

The checkpoint is **stem salvage, not a completed job or automatic resume**: it has no editable `job.json`, and rerunning
SOURCE still starts a new preparation. Failed downloads cannot guarantee that remote-only results are recoverable.
The CLI always attempts bounded session shutdown to avoid leaving GPU charges running. If `session_stopped` is false,
use the recorded session/auth with `uv run colab --auth=AUTH stop --session SESSION_NAME` and confirm shutdown.
Successful preparation removes its temporary recovery directory once shutdown is confirmed.

## Preparation options

```bash
uv run karaoke ./song.flac --title "Song" --artist "Artist" --language en
uv run karaoke YOUTUBE_URL --lrclib-id 123456
uv run karaoke YOUTUBE_URL --no-lrclib --whisper-model large-v3
uv run karaoke ./song.flac --background-image ./background.png --resolution 720p
```

YouTube URLs copied with Windows-style escapes such as `watch\?v\=VIDEO_ID` are normalized automatically. Prefer the
canonical quoted form when entering a URL manually: `"https://www.youtube.com/watch?v=VIDEO_ID"`.

| Option | Default | Purpose |
|---|---:|---|
| `--language` | `en` | Whisper language code; CTC accepts common two-letter codes or ISO 639-3. |
| `--title` | source metadata | Track title override for LRCLIB. |
| `--artist` | source metadata | Artist override for LRCLIB. |
| `--album` | source metadata | Album override for LRCLIB. |
| `--lrclib-id` | automatic | Force one LRCLIB record. |
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

When `--language auto` is used and the source metadata does not identify a language, preparation uses the Faster
Whisper fallback because CTC requires an explicit ISO language code.

Preparation always stops before rendering so LyricsEditor corrections remain an explicit human approval step.

## Authentication

Confirm the project-managed Colab CLI is authenticated:

```bash
uv run colab version
uv run colab sessions
```

Set `HF_TOKEN` in `.env` or the shell when Hugging Face downloads require authentication. Cookies default to the
ignored project file `cookies.txt`. Both are credentials and must not be committed or published.

If Colab reports `HTTP 412 Precondition Failed` or `TooManyAssignmentsError`, stop an existing named runtime:

```bash
uv run colab stop --session SESSION_NAME
```

If `uv run colab sessions` shows an assignment named `[?]`, the server still has a runtime that is missing from the
local session state. Release it by replacing `ENDPOINT` with the endpoint printed after `[?]`:

```bash
uv run python -c "from colab_cli.common import state; state.client.unassign('ENDPOINT')"
uv run colab sessions
```

The project pins `google-colab-cli==0.6.0` with `jupyter-kernel-client==0.15.0` because that CLI still uses the
pre-1.0 kernel client API.

## Limits

- LyricsEditor is external and browser-sandboxed; exported YAML must be moved back into the prepared job manually.
- Agents and overlapping background vocals are supported, but automatic singer identification, translations, and
  romanization are out of scope.
- LRCLIB matching can fail for incomplete or noisy source metadata; use `--lrclib-id` when exact selection matters.
- Music audio and lyrics may receive Content ID claims, regional blocks, or takedown requests.
- Colab transfer size and concurrent runtime limits depend on the account.

## Thumbnails dinámicos (local, sin Colab)

Genera miniaturas PNG de 1280×720 siguiendo `references/thumbnails/thumbnail_complete.png`: artista arriba,
título condensado en marfil con textura y sombra, etiqueta LYRICS/KARAOKE con líneas laterales y logo
abajo a la izquierda. Reutiliza `references/thumbnails/background.png` y `logos/thumbnail.png`.
El texto se dibuja de nuevo para cada canción; `song_and_artist_name.png` es solo una referencia.

```bash
# Crear ambas versiones sin preparar audio ni un job:
uv run karaoke thumbnail --title "ALRIGHT" --artist "ASHES TO AMBER"

# Otra canción y carpeta de salida:
uv run karaoke thumbnail --title "Tu canción" --artist "Tu artista" \
  --mode karaoke --output-dir outputs/mi-cancion

# Leer title y source.artist (o metadata.artist) de un trabajo existente:
uv run karaoke thumbnail outputs/JOB_ID

# Personalizar recursos o generar a 1920×1080:
uv run karaoke thumbnail --title "Tu canción" --artist "Tu artista" \
  --background references/thumbnails/background.png --logo logos/thumbnail.png --width 1920
```

Este comando independiente conserva el fondo de referencia salvo que pases `--background`;
`karaoke render` usa los temas dinámicos descritos arriba; `--theme job` conserva el fondo del trabajo.

Sin job, los resultados quedan en `outputs/thumbnails/ARTISTA-TITULO/`
(`thumbnail_lyrics.png` y `thumbnail_karaoke.png`); con job, en `JOB_DIR/thumbnails/`. Repetir el comando reemplaza los PNG
con esos nombres: usa `--output-dir` diferente para conservar cada canción. No modifica `job.json`.

- `--mode both|lyrics|karaoke`: por defecto genera ambos modos.
- `--no-logo` y `--no-texture`: omiten el logo o la textura del texto.
- `--title-font ARCHIVO.ttf` y `--artist-font ARCHIVO.ttf`: permiten usar otras fuentes locales.
- `--width`: múltiplo de 16 entre 640 y 3840; altura automática en 16:9.
- Títulos largos se reparten en dos líneas y se ajustan al espacio disponible. También puedes pasar
  un salto de línea explícito. Máximo 200 caracteres por campo y dos líneas de título.

Se incluyen Anton y Montserrat con sus licencias SIL OFL en `src/karaoke_app/assets/fonts/`;
no requiere descargar fuentes durante la generación. Proceden de
[Google Fonts](https://github.com/google/fonts/tree/main/ofl).
La tipografía y la textura son una aproximación reproducible: la referencia rasterizada no contiene
la fuente original. El fondo se reutiliza como imagen fija y el logo conserva el diseño del PNG
proporcionado, que difiere del logo en mayúsculas del ejemplo final. Para una instalación fuera del
repositorio, pasa las rutas de fondo y logo explícitamente.
