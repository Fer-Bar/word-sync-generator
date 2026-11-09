# Lyrics Generator

Genera videos de karaoke y lyrics a partir de una URL de YouTube o un archivo local.
La CLI prepara audio y letras en Google Colab, descarga un trabajo editable y permite
renderizarlo varias veces sin repetir la separación de voces ni la alineación.
Configura fondos animados, imágenes o videos, colores de letras, estilos tipográficos,
resolución, miniaturas, intros y marcas de agua desde la CLI y `job.json`.

- **Karaoke:** audio instrumental y letras con desplazamiento y resaltado por palabra.
- **Lyrics:** audio original y letras en páginas fijas.
- Ambos modos generan video, subtítulos, miniatura e intro cuando hay espacio antes de las voces.

## Requisitos e instalación

Ejecuta los comandos desde la raíz del repositorio. Necesitas Python 3.12, `uv`,
conexión a Internet y acceso a un runtime GPU de Google Colab. La GPU disponible depende de tu cuenta.

```bash
uv sync --dev
source .venv/bin/activate
uv run colab version
uv run colab sessions
```

Comprueba que la CLI de Colab puede acceder a tus sesiones antes de preparar una canción.
Para generar vistas previas locales, instala también Chromium:

```bash
uv run playwright install --with-deps chromium
```

Las variables opcionales están en [.env.template](.env.template). Usa `.env` para credenciales
como `HF_TOKEN` y el token de Genius. Las cookies de YouTube se leen de `cookies.txt`;
puedes indicar otra ruta con `--cookies` u omitirlas con `--no-cookies`.
No publiques esos archivos. Consulta [problemas de acceso y recuperación](docs/troubleshooting.md).

Las subidas a Colab registran el tamaño y su estimación en base64. Los paquetes de
64 MiB o más muestran un aviso antes de crear la sesión (umbral orientativo, no un
límite del servidor). Los errores distinguen un rechazo por tamaño de un HTTP 400
de causa no confirmada; consulta [errores de subida](docs/troubleshooting.md#errores-al-subir-archivos).

## Preparar, revisar y renderizar

### 1. Preparar la canción

```bash
uv run karaoke "https://www.youtube.com/watch?v=VIDEO_ID" --language es
```

Las URLs de YouTube se descargan automáticamente en tu máquina antes de crear la sesión
GPU. Después se suben el audio y sus metadatos a Colab, evitando el bloqueo antibots de
la descarga desde Colab. Se necesita [Deno](https://deno.com/) disponible en el PATH;
`yt-dlp` se instala con `uv sync`. Primero se prueba sin autenticación y, si falla, se
reintenta con `cookies.txt` (salvo `--no-cookies`). Las cookies usadas localmente no se
suben a Colab. Si falla la descarga local, no se crea la sesión GPU. Las URLs de otros
servicios conservan su descarga remota. Los archivos temporales se limpian al finalizar.

También puedes usar audio o video local y proporcionar los metadatos:

```bash
uv run karaoke ./cancion.flac --title "Mi canción" --artist "Artista" --language es
```

El comando descarga el trabajo en `outputs/JOB_ID/` y termina. No renderiza todavía.
Si tienes la letra correcta en un TXT, añádelo con `--lyrics-text ./letra.txt`.
Consulta las [opciones de preparación y letras](docs/preparation.md).

### 2. Revisar las letras

El archivo editable es `outputs/JOB_ID/lyrics.lyricsfile.yaml`. Para corregirlo en
[LyricsEditor](https://dotslashgabut.github.io/lyricseditor/):

1. Carga `vocals.flac` y `lyrics.lyricsfile.yaml` del trabajo.
2. Revisa texto y sincronización; `Alt+N` y `Alt+P` recorren palabras con baja confianza.
3. Exporta **LyricsFile YAML** y reemplaza el archivo del trabajo.

LyricsEditor es externo y opcional. Un nuevo render reutiliza los tiempos guardados;
no corrige automáticamente errores de alineación.

### 3. Renderizar

```bash
uv run karaoke render outputs/JOB_ID --mode both
```

Usa `--mode lyrics` o `--mode karaoke` para producir solo uno. Los resultados se descargan
en `outputs/JOB_ID/renders/FECHA-MODO/`, con MP4, subtítulos, miniaturas y configuración efectiva.

**Conservación de variantes:** después de una descarga correcta se eliminan renders anteriores
que ya tienen reemplazo, conservando el último video de cada modo. Copia fuera de `renders/`
las variantes que quieras guardar antes de volver a renderizar.

## Personalizar y previsualizar

Los trabajos nuevos usan el estilo Plus y un fondo fluido. `configure` guarda preferencias
en `job.json`; las opciones de `render` afectan solo a esa ejecución.

```bash
uv run karaoke configure outputs/JOB_ID --background-style fluid --cover portada.jpg
uv run karaoke preview outputs/JOB_ID --mode lyrics --start 15 --duration 8 \
  --output outputs/previews/lyrics.mp4
uv run karaoke render outputs/JOB_ID --mode lyrics
```

El preview local muestra letras y fondo; el render final añade intro y marca de agua.
Para previsualizar trabajos con fondo estático, indica un fondo procedural con `--background-style`.
Las [opciones visuales](docs/visuals.md) incluyen fondos propios, colores, logos, miniaturas y FOMO.
Usa `--theme forest` al renderizar para un fondo verde bosque oscuro, con variaciones
del mismo verde sobre una base casi negra; combina con `--background-style fluid` para movimiento suave.

## Archivos del trabajo

| Archivo | Uso |
| --- | --- |
| `job.json` | Configuración de audio, video, fondo y estilo. |
| `lyrics.lyricsfile.yaml` | Texto editable y tiempos por palabra. |
| `vocals.flac`, `instrumental.flac` | Voces para revisión y acompañamiento para karaoke. |
| `original_audio.*` | Audio utilizado en modo lyrics. |
| `reference.txt`, `lyrics_reference.json` | Letra de referencia y su procedencia, cuando están disponibles. |
| `alignment.json`, `lyrics_validation.json` | Diagnóstico de alineación y discrepancias. |
| `performance.json` | Medición de la preparación o del render correspondiente. |
| `renders/` | Resultados finales. |

## Recursos de marca y archivos locales

`logos/` incluye los tres recursos de SingLume: `banner.png`, `principal_logo.png` y
`thumbnail.png`. Los logos personalizados adicionales y las imágenes de referencia en
`references/` son locales y quedan excluidos de Git, al igual que `outputs/`.

Las carpetas `*.recovery/` conservan artefactos si una preparación falla, se cancela o
no se confirma el cierre de Colab. Se eliminan al completar correctamente el proceso y
quedan excluidas de Git incluso al usar otra carpeta de salida. Antes de borrarlas,
comprueba el cierre de la sesión y si necesitas rescatar archivos; consulta
[fallos de preparación](docs/troubleshooting.md#fallos-de-preparación).

## Documentación

- [Preparación, referencias y formato de letras](docs/preparation.md).
- [Fondos, estilos, miniaturas y migración de trabajos](docs/visuals.md).
- [Autenticación, errores y recuperación](docs/troubleshooting.md).
- [Desarrollo, pruebas y mediciones](docs/development.md).

Para consultar todas las opciones de un comando:

```bash
uv run karaoke --help
uv run karaoke render --help
uv run karaoke configure --help
```

## Limitaciones

La alineación automática puede requerir correcciones; no identifica cantantes automáticamente.
El render MP4 usa Braccato en Chromium; la animación del ASS exportado es una aproximación.
El modelo CTC predeterminado tiene licencia **CC-BY-NC-4.0**; revisa sus condiciones
antes de usarla comercialmente. Las fuentes y el motor visual conservan sus licencias propias.

## Tecnologías y proyectos

| Proyecto | Uso |
| --- | --- |
| [Python](https://www.python.org/) y [uv](https://github.com/astral-sh/uv) | CLI, servicios y gestión del entorno. |
| [Google Colab CLI](https://github.com/googlecolab/google-colab-cli) | Preparación y render en runtimes de Colab. |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Adquisición de audio y metadatos. |
| [Demucs](https://github.com/facebookresearch/demucs) | Separación de voces e instrumental. |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Transcripción con tiempos por palabra. |
| [CTC Forced Aligner](https://github.com/MahmoudAshraf97/ctc-forced-aligner) | Alineación acústica de letras de referencia. |
| [Braccato](https://www.npmjs.com/package/@braccato/core) | Presentación y animación de letras sincronizadas. |
| [Playwright](https://github.com/microsoft/playwright) y Chromium | Captura de las escenas de letras. |
| [FFmpeg](https://ffmpeg.org/) | Procesamiento de audio y composición del video. |
| [Pillow](https://python-pillow.github.io/), [NumPy](https://numpy.org/) y [PyYAML](https://pyyaml.org/) | Recursos gráficos, cálculos y formato de letras. |
| [LyricsGenius](https://github.com/johnwmillr/LyricsGenius) | Consulta de letras en Genius. |
| [LyricsEditor](https://github.com/dotslashgabut/lyricseditor) | Editor web externo para revisar letras y tiempos. |

Las referencias de letras proceden de [LRCLIB](https://lrclib.net/), [Genius](https://genius.com/)
o de archivos aportados por el usuario. Su disponibilidad y contenido dependen de cada fuente.

## Licencia

El código propio se distribuye bajo [Apache-2.0](LICENSE). Las bibliotecas, modelos y fuentes
mantienen sus licencias; consulta las [atribuciones y condiciones de terceros](THIRD_PARTY_NOTICES.md).


## Auditoría de sincronización

El [análisis del desfase de FOR SIXXX IN THE MORNIN](docs/alignment-audit-20261105.md) documenta
un fallo local aceptado por los controles de CTC/ASR, las pruebas realizadas y los
criterios de corrección sin regresiones. Es un diagnóstico; aún no cambia la alineación.

## Estado de la alineación

La recuperación experimental probada con Jessie Reyez fue revertida tras regresiones
observadas en otras canciones. Se conserva la lógica de alineación anterior a ese
experimento. Los resultados requieren revisión: las pruebas automáticas no certifican
precisión acústica. Véase la [auditoría del desfase](docs/alignment-audit-20261105.md).

### Console progress and appearance options

Prepare, choose an appearance, validate, and render:

```sh
uv run karaoke source "https://www.youtube.com/watch?v=VIDEO_ID" --language es
uv run karaoke configure outputs/JOB_ID --interactive
uv run karaoke render outputs/JOB_ID --dry-run
uv run karaoke render outputs/JOB_ID
```

The interface is in English. `source` shows video metadata before the audio download
finishes, then download progress, lyric source, preparation stages, and output paths.
The existing `uv run karaoke URL` syntax still works. Artist and channel are shown
separately; missing song metadata can be supplied with `--title` and `--artist`.

`configure --interactive` starts from saved settings. Enter keeps the current value;
the final confirmation saves `job.json` atomically. Cancelling or pressing Ctrl+C
leaves the job unchanged. Procedural backgrounds can be previewed in a temporary
three-second video before saving. Open the displayed path while the assistant is
waiting; the preview is removed when you continue. Background image files must be
inside the job folder; logo and artwork palette paths may point to external files.

Flags remain available for scripts:

```sh
uv run karaoke configure outputs/JOB_ID --visual-style plus --background-style fluid
uv run karaoke configure outputs/JOB_ID --background-color '#123456'
uv run karaoke render outputs/JOB_ID --mode lyrics --background-style cosmic-sand --seed 42
```

Omitted options preserve saved settings. `configure` persists overrides; `render`
applies them to that run only. `render --dry-run` validates required assets and timed
lyrics, and displays the resolved appearance without writing files or starting Colab.
It does not check GPU availability, authentication, or remote dependencies.
`configure --help` and `render --help` group appearance and watermark options.

Console output reports meaningful stages and outcomes, not provider queries,
candidate lists, installation commands, or alignment internals. Download percentages
use byte counts; encoding and frame progress use measured work. Other stages show
activity and elapsed time. On Colab, the startup indicator is replaced by the actual
stage: opening the project, generating the background, installing browser support,
drawing frames, finalizing the video, and packaging results. Frame progress includes
completed/total counts. If no stage update arrives for 60 seconds, the CLI reports
that silence and the last known stage; it does not claim that work is still advancing.
In an interactive terminal, the active stage and counters update in place. Completed
stages leave one summary with their duration. `Colab ready` includes connection,
uploads, and pipeline startup; sub-second stages show `<1s`. Nested frame/install steps do not leave
redundant start/done lines. When output is redirected, stage changes, rate-limited
percentage milestones, and results are printed. `NO_COLOR=1` disables colors. Interactive configuration requires a terminal.

Recoverable provider attempts stay in diagnostics. Remaining lyric validation issues
are summarized after local recovery, with the report path. GPU fallbacks, missing fonts,
and a session that could not be stopped remain visible because they affect the result
or require action. OAuth authorization URLs and code prompts remain available.

Each execution keeps redacted diagnostics in `.karaoke/logs/` (excluded from Git).
Errors show the operation and the underlying exception or tool error, then point to
the full log. Known Colab session-limit errors include a suggested action.
`--verbose` also displays technical details live. These
logs are local and are not automatically deleted. Help and dry runs do not create logs.


## Desarrollo y comprobaciones

El workflow `Checks` usa Python 3.12 y ejecuta estas comprobaciones:

```bash
uv sync --locked --dev --python 3.12
uv run playwright install --with-deps chromium
uv run ruff check .
uv run pytest -q
uv build
```

Las pruebas locales de composición usan el binario incluido en `imageio-ffmpeg`,
también al medir el progreso de codificación. Las pruebas de recorte y de marca de
agua vacían `PATH` para detectar dependencias accidentales de un FFmpeg del sistema.
Las pruebas de marca de agua no instalan ni descargan fuentes del sistema.
Esto no cambia los requisitos de FFmpeg ni la instalación de fuentes en Colab.

### Media storage

Uploads use audio-only inputs, compress integer WAV losslessly, and include only
what the selected render mode needs. Successful remote runs discard their own
scratch files after the result ZIP is committed. This cleanup preserves original
inputs, project audio and existing exports. The separate render-version retention
rules above still apply. See [media and cache policy](docs/media-cache.md).
