# Lyrics Generator

Prepara audio y letras sincronizadas, revisa la letra y genera videos de **karaoke**
(instrumental) o **lyrics** (audio original). La preparación se reutiliza: cambiar el fondo,
la tipografía o la marca de agua no requiere separar voces ni alinear otra vez.

## Empezar desde el navegador

Abre [Generar un video con letras](notebooks/generate_video.ipynb) en Google Colab y
selecciona una GPU T4. El paso 1 descarga el motor de su versión y verifica el SHA-256
fijado en el cuaderno. Si la entrega local aún no está publicada, pide subir el wheel
que está junto al cuaderno en `notebooks/`.
Sigue los pasos: **audio → preparación → revisión → video → descarga**.
No necesitas terminal, construir paquetes ni escribir rutas Python.

Usa siempre el cuaderno y el wheel de la misma entrega. Ejecuta las celdas individualmente:

1. **Iniciar:** elige **Modelo** (`small`, `medium` o `large-v3`), instala el motor y comprueba la GPU.
2. **Subir canción:** bajo este bloque, ejecuta **2a o 2b, solo uno**.
   En 2a pulsa ▶ y sube el archivo local; en 2b pega el enlace de
   YouTube antes de ▶. Si necesitas cookies, marca **Subir_cookies**: al ejecutar aparecerá
   el botón nativo para subir `cookies.txt`. Espera **Archivo listo**.
3. **Datos:** pulsa ▶ para detectar el idioma y después edita título, artista e idioma;
   álbum y TXT son opcionales. La detección usa el modelo elegido al iniciar, sin otro modelo
   pequeño. Si no encuentra evidencia suficiente, selecciona el idioma manualmente.
   La letra se busca automáticamente. **Subir letra TXT** permite aportar tu archivo
   en su lugar; **Quitar** aparece solo cuando hay uno recibido y restaura la búsqueda.
4. **Preparar:** reutiliza el modelo y sus pesos descargados; respeta el idioma final del formulario.
   La revisión opcional **4b** sigue este orden:
   descargar voces → descargar YAML → abrir LyricsEditor → subir corrección.
   La importación comprueba título, artista conocido, duración y límites de tiempos contra
   el audio del proyecto antes de reemplazar la letra; conserva un respaldo de la anterior.
   En **4c.1**, pulsa ▶ para abrir el diseño guardado. Abrirlo sin editar no requiere aplicarlo
   ni invalida el vídeo anterior. Puedes elegir un único **Fondo**: Clásico, Fluido, Cósmico, Color,
   Imagen, Vídeo o Vídeo de origen. Cada opción muestra únicamente sus ajustes;
   los colores tienen paleta, muestra visual y selector personalizado.
   Ejecuta **4c.2** para aplicar el diseño y subir la imagen/vídeo cuando corresponda.
5. **Generar:** elige modo y calidad antes de ▶. Conserva el diseño guardado, incluso si omites 4c.
6. **Descargar:** elige el archivo antes de ▶; MP4 es el valor predeterminado.

Los formularios junto a ▶ se eligen antes de ejecutar. Los paneles del paso 3 y de 4c.1
se editan después de abrirlos. Cambiar el diseño no repite la preparación; aplica los cambios
en 4c.2 antes de generar.

Editar los datos no borra el último proyecto ni vídeo completos. Si ya no corresponden
a los datos actuales, revierte los cambios o repite el paso 4 antes de generar.
Un intento fallido conserva los resultados anteriores para descargarlos.

El notebook usa el mismo motor que la CLI, dentro de tu sesión actual. La CLI sigue
disponible para automatización y proyectos locales. [Instalación, distribución y límites](docs/notebooks.md).

## Empezar con la CLI

Necesitas Python 3.12+, [uv](https://docs.astral.sh/uv/) y acceso a Google Colab con GPU.
Desde el repositorio:

```bash
uv sync --dev
uv run colab sessions
uv run karaoke source ./cancion.flac --title "Mi canción" --artist "Artista" --language es
```

La preparación descarga un proyecto en `outputs/JOB_ID/`, sin renderizar aún.
También acepta URLs de YouTube. Se descargan primero en tu máquina y requieren
[Deno](https://deno.com/) en el PATH; un fallo de descarga no abre una sesión GPU.
Para una letra revisada añade `--lyrics-text ./letra.txt`.

La instalación remota y la preparación comparten `--timeout` (14 400 segundos por defecto).
Los requisitos viajan en el paquete de entrada y se instalan dentro de `colab exec`,
con salida de diagnóstico en tiempo real. La CLI crea `/content/karaoke-env`, comprueba
sus dependencias y ejecuta allí el motor, sin mezclarlo con Torch/TorchVision del Python
de Colab. El notebook instala sus requisitos en el paso 1; el lanzador reutiliza ese
entorno aislado al preparar o renderizar.
Las rutas `/content/...` de los logs pertenecen a Colab; los resultados se descargan
a `outputs/` en tu máquina (o al directorio elegido con `--output-dir`).

**La preparación prioriza la calidad y siempre ajusta la letra al audio:** usa Whisper
como evidencia independiente y CTC para alinear el texto conocido, también cuando LRCLIB
aporta un LyricsFile con word sync. Los tiempos del proveedor sirven como referencia;
no se aceptan como resultado final solo porque coincidan los metadatos. Los tiempos
incompatibles se excluyen de las ventanas de recuperación, pero se conserva la letra.
Se preservan el texto y la estructura de la variante seleccionada; `plainLyrics` no
sobrescribe un LyricsFile nativo. El registro original queda en `lrclib_record.json`.
Sin letra utilizable, se transcribe. Un TXT explícito mantiene prioridad. Las recuperaciones
con tiempos estimados se identifican en el diagnóstico. Voces e instrumental se generan
para la revisión y ambos modos de vídeo. La comprobación acústica ya no es opcional:
no hace falta una casilla ni un flag. El antiguo `--verify-word-timings` sigue aceptándose.
Para usar un YAML ya terminado sin repetir este procesamiento, renderiza el proyecto existente.

El paquete también puede instalarse desde el wheel de `notebooks/`, sin un checkout junto
al ejecutable. En ese caso los archivos locales y las salidas se buscan en el directorio
actual. [Instalación portable y notebook](docs/notebooks.md).

### Una sola entrega

`notebooks/` contiene únicamente `generate_video.ipynb` (fuente editable) y su
`lyrics_generator-<versión>-py3-none-any.whl` (motor generado, ignorado por Git).
Conserva la interfaz de pasos separados **2a/2b**, revisión **4b** y diseño **4c**.
No se mantienen copias del cuaderno en `dist/`.

Después de cambiar el motor o preparar una versión, ejecuta:

```bash
uv run python scripts/build_notebook.py
uv run python scripts/build_notebook.py --check
```

La versión se cambia solo en `pyproject.toml`; el comando genera el wheel y actualiza
la versión y su SHA-256 en el cuaderno. Elimina wheels anteriores de esa carpeta y
comprueba código, requisitos de Python, dependencias y extras del paquete.
CI y publicación usan el mismo comando. Un tag solo publica cuando todos los checks
de ese mismo commit pasan; el workflow de publicación reutiliza ese resultado.
Los audios locales se conservan en `inputs/notebook-examples/` y los resultados en
`outputs/notebook-examples/`, separados de la entrega.

### 1. Revisar las letras

Abre `vocals.flac` y `lyrics.lyricsfile.yaml` del proyecto en
[LyricsEditor](https://dotslashgabut.github.io/lyricseditor/). Corrige texto y tiempos,
exporta **LyricsFile YAML** y reemplaza la letra del proyecto. La revisión es necesaria:
los controles automáticos no certifican precisión acústica ni identifican cantantes.

### 2. Configurar y previsualizar

```bash
uv run karaoke configure outputs/JOB_ID
uv run karaoke status outputs/JOB_ID
uv run karaoke validate outputs/JOB_ID
```

`configure` guarda las preferencias del proyecto; los flags de `render` afectan solo a esa
corrida. Puedes partir de `--preset fluid`, `cosmic` o `classic`, y cambiar título, artista,
resolución, fps y modo por secciones. No necesitas editar archivos de configuración a mano. Enter conserva el valor
actual y cancelar el asistente no guarda cambios. `validate` y `render --dry-run` validan archivos y letras,
sin iniciar Colab ni comprobar GPU/autenticación.

Para una vista previa local instala Chromium una vez:

```bash
uv run playwright install --with-deps chromium
uv run karaoke preview outputs/JOB_ID --mode lyrics --start 15 --duration 8 --output preview.mp4
```

El preview muestra letras y fondo; la composición final añade intro y, solo si eliges
`--logo ./mi-logo.png`, tu marca de agua. No se distribuyen logos personales.
[Opciones visuales](docs/visuals.md).

### 3. Renderizar

```bash
uv run karaoke render outputs/JOB_ID --mode both
```

Usa `--mode lyrics` o `--mode karaoke` para producir uno solo. Los MP4, subtítulos,
miniaturas y datos de cada render quedan en `outputs/JOB_ID/renders/`.
Las variantes anteriores se conservan. La limpieza es explícita y reversible:

```bash
uv run karaoke cleanup outputs/JOB_ID                            # Inventario
uv run karaoke cleanup outputs/JOB_ID RENDER_ID --apply          # Mover a la papelera
uv run karaoke cleanup outputs/JOB_ID RENDER_ID --restore --apply # Recuperar
```

No es un borrado permanente ni libera espacio de disco. Conserva una copia del proyecto.

## Cómo está organizado

| Parte | Responsabilidad |
| --- | --- |
| `cli.py` | Comandos, transferencias y sesiones remotas. |
| `notebook.py` / `notebook_runner.py` | Ejecución en la sesión abierta y adaptación de los controles del cuaderno. |
| `rendering.py` | Validación de entradas, subtítulos y paquete de render compartidos. |
| `visual_config.py`, `lyrics_file.py`, `job_document.py` | Configuración visual, letras y validación del proyecto. |
| `colab/` | Lanzador aislado y procesamiento de audio/video. |

La interfaz no contiene una segunda implementación del motor. Las pruebas del motor
y de la CLI protegen el comportamiento compartido; el notebook se comprueba ejecutándolo.
Consulta [desarrollo y arquitectura](docs/development.md) para los límites de cada módulo.

## Archivos y credenciales

- `lyrics.lyricsfile.yaml`: letra y tiempos editables.
- `vocals.flac`, `instrumental.flac`, `original_audio.*`: material para revisión y render.
- `alignment.json`, `lyrics_validation.json`, `performance.json`: diagnóstico y tiempos.
- `renders/`: videos y artefactos de salida.

Las variables opcionales están en [.env.template](.env.template). No publiques `.env`,
tokens, cookies ni los archivos de tus canciones. `--no-cookies` omite cookies de YouTube.
Las subidas grandes muestran un aviso, no una garantía sobre el límite de Colab.
La consola muestra progreso; `--verbose` amplía los detalles. Los registros privados quedan
en `.karaoke/logs/`. Antes de borrar una carpeta `*.recovery/`, comprueba si contiene
archivos recuperables y si la sesión remota se cerró.

## Documentación

- [Preparación, referencias y letras](docs/preparation.md).
- [Proyectos, presets y configuración por secciones](docs/project-cli.md).
- [Fondos, tipografía, logos y previews](docs/visuals.md).
- [Audio, temporales y recuperación](docs/media-cache.md).
- [Notebook y paquete portable](docs/notebooks.md).
- [Errores, autenticación y recuperación](docs/troubleshooting.md).
- [Desarrollo y arquitectura](docs/development.md).
- [Pruebas de integración y sus límites](docs/testing.md). CI prepara Chromium y
  FFmpeg, y descarga Switzer desde Fontshare con hashes fijados; no acepta omisiones
  por falta de la fuente. Switzer sólo se guarda en el runner, sin caché compartida ni redistribución.
- [Auditoría de sincronización](docs/alignment-audit-20261105.md): diagnóstico histórico,
  no garantía de precisión. La recuperación experimental con regresiones fue revertida.

Consulta `uv run karaoke --help` o `uv run karaoke COMANDO --help` para las opciones completas.
La interfaz de la CLI está en inglés.

## Licencias

Código propio: [Apache-2.0](LICENSE). El modelo CTC predeterminado tiene licencia
**CC-BY-NC-4.0**: revisa sus condiciones antes de usarlo comercialmente.
Demucs, faster-whisper, yt-dlp, Braccato, FFmpeg, las fuentes y otras dependencias mantienen
sus condiciones. [Atribuciones y licencias de terceros](THIRD_PARTY_NOTICES.md).
