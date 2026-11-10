# Lyrics Generator

Prepara audio y letras sincronizadas, revisa la letra y genera videos de **karaoke**
(instrumental) o **lyrics** (audio original). La preparación se reutiliza: cambiar el fondo,
la tipografía o la marca de agua no requiere separar voces ni alinear otra vez.

## Empezar desde el navegador

Abre [Generar un video con letras](notebooks/generate_video.ipynb) en Google Colab y
selecciona una GPU T4. Recibe el paquete `.whl` del responsable del proyecto, súbelo
cuando el cuaderno lo pida y sigue los pasos: **audio → preparación → revisión → video → descarga**.
No necesitas terminal, construir paquetes ni escribir rutas Python.

El flujo principal usa **audio local y búsqueda automática de letras**: completa título,
artista e idioma (álbum opcional), prepara y comprueba el proveedor de la letra y los
tiempos antes de renderizar. El TXT es una alternativa, no un requisito. La entrada
por URL de YouTube sigue disponible en la CLI; en el notebook queda para una etapa posterior.

El paso 1 instala y comprueba la GPU. Ejecuta **2 · Tu canción** para abrir el formulario:
el audio es la entrada principal y **Aportar mi letra · opcional** permite subir o quitar
un TXT. El paso 3 crea las voces, el instrumental y la letra sincronizada; todavía no vídeos.
Revisa la letra y genera el vídeo sin casillas adicionales de confirmación. Cambiar las
entradas invalida la preparación anterior. El diagnóstico de disponibilidad de GPU no
demuestra que un proceso esté usándola en ese momento.
La subida usa el selector nativo de Colab y espera a terminar la transferencia.
La subida del audio y el formulario están en celdas separadas: después de recibir el
archivo, ejecuta «Datos de la canción» para leer sus metadatos y confirmar los campos editables.
El modelo Whisper se elige en el formulario nativo del paso 4, antes de preparar la canción.
El paso 2 acepta archivos locales o un enlace de YouTube con metadatos; si hace falta,
puedes aportar cookies temporales. La celda opcional 4c permite usar un color, imagen
o vídeo como fondo sin repetir la preparación del audio. Usa el notebook con el wheel 0.1.1.
Después de la preparación, la celda opcional 4b permite descargar voces y YAML,
corregirlos en LyricsEditor y subir la
letra corregida sin repetir la preparación. La descarga final predeterminada es MP4.

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

El paquete también puede instalarse desde un wheel construido con `uv build`, sin un checkout junto
al ejecutable. En ese caso los archivos locales y las salidas se buscan en el directorio
actual. [Instalación portable y notebook](docs/notebooks.md).

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

El preview muestra letras y fondo; la composición final añade intro y marca de agua.
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
