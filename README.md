# Lyrics Generator

Genera videos de karaoke y lyrics desde una URL de YouTube o un archivo local.
Prepara audio y letras en Google Colab, revisa la sincronización y configura el
proyecto desde la CLI antes de renderizar. No necesitas editar archivos de
configuración: para corregir las letras y sus tiempos se edita el YAML del proyecto.

- **Karaoke:** audio instrumental y resaltado por palabra.
- **Lyrics:** audio original y letras en páginas fijas.
- El render genera videos, subtítulos, miniaturas y las intros habilitadas.

## Instalar

Usa Python 3.12 y `uv`. Ejecuta los comandos desde la raíz del repositorio:

```bash
uv sync --dev
uv run colab version
uv run colab sessions
```

Necesitas Internet y acceso a un runtime GPU de Colab. La disponibilidad de GPU
depende de tu cuenta. Para URLs de YouTube, instala también [Deno](https://deno.com/);
`yt-dlp` ya es una dependencia del proyecto.

Las variables opcionales están en [.env.template](.env.template). Las cookies de
YouTube se leen de `cookies.txt`; puedes cambiar la ruta con `--cookies` u omitirlas
con `--no-cookies`. No publiques `.env`, cookies ni credenciales. Consulta
[acceso y recuperación](docs/troubleshooting.md).

## Preparar → revisar → configurar → renderizar

### 1. Preparar

```bash
uv run karaoke source "https://www.youtube.com/watch?v=VIDEO_ID" --language es
uv run karaoke source ./cancion.flac --title "Mi canción" --artist "Artista" --language es
```

Cada comando crea un proyecto en `outputs/PROYECTO/`. La preparación separa voces e
instrumental y genera letras con tiempos por palabra; todavía no crea el video.
Las URLs de YouTube se descargan localmente antes de abrir Colab. Si tienes una letra
revisada, añade `--lyrics-text ./letra.txt`.

### 2. Revisar las letras

Abre `lyrics.lyricsfile.yaml` junto a `vocals.flac` en
[LyricsEditor](https://dotslashgabut.github.io/lyricseditor/), revisa texto y tiempos
y exporta **LyricsFile YAML** a la misma carpeta. El editor es externo y opcional.
Un nuevo render usa esos tiempos; no vuelve a transcribir ni alinear la canción.

### 3. Configurar y validar

```bash
uv run karaoke configure outputs/PROYECTO
uv run karaoke status outputs/PROYECTO
uv run karaoke validate outputs/PROYECTO
```

`configure` abre un menú con presets, tipografía, fondo, título y arte, marca de agua,
video y salida. Puedes volver a cada sección, revisar los cambios y guardar. Cancelar
o interrumpir deja el proyecto intacto. El menú no genera previews.

Para scripts, usa opciones explícitas:

```bash
uv run karaoke configure outputs/PROYECTO --preset cosmic --resolution 720p --fps 30 --mode lyrics
uv run karaoke configure outputs/PROYECTO --title "Otro título" --artist "Artista" --no-intro
uv run karaoke configure outputs/PROYECTO --lyrics-active-color '#FFFFFF' --font-size 64
```

Los presets son `fluid`, `cosmic` y `classic`. Las opciones explícitas prevalecen sobre
el preset; las omitidas conservan lo guardado. `status` muestra ajustes, medios y
exportaciones. `validate` comprueba los archivos necesarios y los tiempos de letras
sin iniciar Colab. No comprueba autenticación, cuota de GPU ni dependencias remotas.

La [guía de configuración](docs/project-cli.md) explica las secciones y el uso sin
terminal. Consulta [diseño y render](docs/visuals.md) para fondos, logos y miniaturas.

### 4. Renderizar

```bash
uv run karaoke render outputs/PROYECTO
uv run karaoke render outputs/PROYECTO --mode karaoke
```

Sin `--mode`, se usa el modo guardado, inicialmente `both`. `--mode lyrics` usa el
audio original y `--mode karaoke` el instrumental. Las opciones de apariencia que
se pasan a `render` afectan solo esa ejecución; `configure` las guarda para el futuro.

Los resultados se descargan en `outputs/PROYECTO/renders/FECHA-MODO/`.
**En esta versión, un render correcto elimina variantes anteriores que ya tengan
reemplazo.** Copia fuera de `renders/` las variantes que quieras conservar antes de
volver a renderizar.

## Archivos del proyecto

| Archivo o carpeta | Uso |
| --- | --- |
| `lyrics.lyricsfile.yaml` | Letras y tiempos editables. |
| `original_audio.*`, `instrumental.flac`, `vocals.flac` | Medios para render y revisión. |
| `.karaoke/project.json` | Estado interno administrado por la CLI; no se edita a mano. |
| `reference.txt`, `lyrics_reference.json` | Referencia y procedencia, cuando estén disponibles. |
| `alignment.json`, `lyrics_validation.json` | Diagnóstico de alineación y revisión. |
| `performance.json` | Tiempos y mediciones de la operación. |
| `renders/` | Videos y demás resultados finales. |

Conserva la carpeta completa para volver a renderizar. Las carpetas antiguas con
`job.json` no se cargan ni se convierten automáticamente: prepara un proyecto nuevo
desde la fuente original. Ya no existe el comando `migrate`.

Si una preparación falla, `*.recovery/` conserva los datos disponibles para diagnóstico.
Comprueba que la sesión esté detenida antes de borrar esos archivos. Los logs locales
están en `.karaoke/logs/`; `--verbose` muestra además los detalles en la consola.

## Documentación

- [Preparación y letras](docs/preparation.md).
- [Configuración por secciones y presets](docs/project-cli.md).
- [Diseño, logos y miniaturas](docs/visuals.md).
- [Acceso, errores y recuperación](docs/troubleshooting.md).
- [Desarrollo](docs/development.md) y [pruebas de integración](docs/testing.md).

Usa `uv run karaoke COMANDO --help` para las opciones de cada comando.

## Límites y licencias

La alineación automática necesita revisión y no identifica cantantes automáticamente.
Plus usa Braccato en Chromium; el estilo clásico usa ASS. Los subtítulos exportados no
reproducen todas las animaciones del video. Las pruebas locales no certifican precisión
acústica ni sustituyen una ejecución con modelos y GPU reales.

El código propio usa [Apache-2.0](LICENSE). El modelo CTC predeterminado tiene licencia
**CC-BY-NC-4.0**; revisa sus condiciones antes de usarlo comercialmente. Las bibliotecas,
fuentes y el motor visual conservan sus licencias, recogidas en
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
