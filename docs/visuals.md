# Diseño y render

[Volver al README](../README.md)

## Guardar o probar preferencias

```bash
uv run karaoke configure outputs/JOB_ID --background-style cosmic-sand
uv run karaoke render outputs/JOB_ID --mode both
uv run karaoke render outputs/JOB_ID --background-style fluid --cover portada.jpg
```

`configure` guarda `job.json` de forma atómica y aplica Plus por defecto, sin modificar audio
ni letras. Las opciones de `render` solo afectan esa ejecución. Por defecto, `--theme job`
conserva el fondo guardado, incluidos imágenes y videos.

`--visual-style plus|classic` selecciona las letras. `--background-style fluid|cosmic-sand`
selecciona el fondo procedural; `--cover` extrae dos colores de una imagen local.
En preparación, no combines un fondo procedural con `--background-image` o `--background-color`.

Plus usa Switzer Semibold, letras centradas y resaltado por palabra. Karaoke desplaza las frases;
lyrics usa páginas fijas. Switzer se descarga con su licencia en `~/.cache/karaoke/fonts/`.
Braccato se incluye en el repositorio con su licencia y procedencia en
[PROVENANCE.json](../src/karaoke_app/assets/braccato/PROVENANCE.json).

## Paletas y colores de las letras

`--theme aurora|sunset|synthwave|stellar|random` cambia la paleta del render.
`random` selecciona tema y semilla para compartirlos entre los artefactos; los valores
quedan en `render-settings.json`. Usa el tema elegido y `--seed N` para repetirlos.
`--theme even-better-lyrics-plus` aplica Plus y fondo fluido juntos.

En `job.json`, `style.lyrics_colors.active` cambia el color del resaltado y
`style.lyrics_colors.inactive` configura el color pendiente del karaoke:

```json
{"lyrics_colors": {"active": "#FFD34D", "inactive": "#E8E8E8"}}
```

El fragmento corresponde al objeto `style`. El modo lyrics mantiene su propio tratamiento
del texto inactivo; no presupongas que ambos modos muestran la misma combinación.

## Fondos propios

Copia el recurso dentro del trabajo y configura `background` en `job.json`:

```json
{"kind": "video", "path": "paisaje.mp4", "crop_right": 0.12, "overlay_opacity": 0.25}
```

También admite `kind: "image"`, con una ruta de imagen, o
`{"kind": "solid", "color": "#0B1020"}`. Las rutas del fondo son relativas al trabajo.
`overlay_opacity` oscurece de 0 a 1; no cambia el tono. `crop_right` recorta de 0 a 0.5 del
ancho original antes de ajustar el fondo sin deformarlo; puede haber recorte vertical adicional.

El video se repite y su audio se ignora. El render no crea un fundido entre final e inicio:
prepara previamente un bucle continuo si necesitas evitar el salto. Renderiza con
`--theme job` y omite `--background-style` para conservar el recurso.

## Previsualizar

```bash
uv run karaoke preview outputs/JOB_ID --mode karaoke --start 15 --duration 8 \
  --output outputs/previews/karaoke.mp4
uv run karaoke background examples/cosmic-background.json --output outputs/cosmic-preview.mp4
```

`preview` requiere Chromium, usa el instrumental para karaoke y el audio original para lyrics.
Genera MP4, ASS y JSON; no sobrescribe resultados existentes. Muestra letras y fondo, sin la
intro ni la marca del render final. Para fondos estáticos, selecciona un fondo procedural
con `--background-style` al previsualizar.

`background` genera solo el fondo, sin audio ni letras. Acepta un directorio de trabajo,
un `job.json` o una configuración independiente como
[cosmic-background.json](../examples/cosmic-background.json). Permite recortar tiempo con
`--start` / `--duration` y ajustar `--width`, `--height` y `--fps` sin modificar la configuración.

## Controles del fondo cósmico

El objeto `background` usa `kind: "cosmic"`. Preview y Colab comparten generador y semilla.

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

Un preview recortado no necesariamente cierra el bucle. Para probar parámetros, usa primero
fragmentos cortos y resolución baja: la generación del fondo usa CPU.

## Miniaturas, intro y logo

`render` genera las miniaturas y las capas transparentes de intro automáticamente.
El título procede de `title`; el artista, de `source.artist` o `metadata.artist`.
`intro.title` / `intro.artist` permiten sobrescribirlos.

La intro dura hasta cinco segundos por defecto y termina antes de la primera voz.
Si no hay espacio, se omite. Configura `intro.enabled`, `intro.duration`, `intro.start` e
`intro.end` en `job.json`; desactivar la intro no desactiva las miniaturas.

`--align start|center|end` alinea título y artista, sin cambiar la alineación de las letras cantadas.
Para una miniatura independiente de la intro, añade a `job.json`:

```json
"thumbnail": {"time": 3, "align": "end"}
```

`time` selecciona el instante del fondo; en videos debe estar dentro del clip.
Sin esa opción se usa el instante cero. `background.png` conserva el instante cero.

```bash
uv run karaoke render outputs/JOB_ID --logo logos/banner.png --logo-position top_left
uv run karaoke thumbnail outputs/JOB_ID --mode lyrics --align end
uv run karaoke thumbnail --title "Mi canción" --artist "Artista" --output-dir outputs/miniaturas
uv run karaoke intro outputs/JOB_ID --mode lyrics
```

Los logos reutilizables se guardan en `logos/`. `--no-logo` desactiva la marca.
`thumbnail` es local y genera PNG de 1280×720 por defecto; admite fondo, fuentes y ancho propios.
Con trabajo, escribe en `JOB_DIR/thumbnails/`; sin trabajo, en `outputs/thumbnails/ARTISTA-TITULO/`.
Repetirlo reemplaza esos PNG; utiliza `--output-dir` para guardar variantes.
`intro` genera una tarjeta transparente independiente. Ninguno necesita ejecutar Colab.

Los resultados del render incluyen `thumbnails/`, las capas habilitadas de `intro/`,
`background.png` y `render-settings.json`. El bucle temporal `background.mp4` no se descarga.

## FOMO y fotocopia

```bash
uv run karaoke configure outputs/JOB_ID --graphic-style fomo --title-layout wide --align center
uv run karaoke configure outputs/JOB_ID --graphic-style fomo-xerox --graphic-palette dark
uv run karaoke render outputs/JOB_ID --mode lyrics
```

FOMO usa Abril Fatface en título y artista, fondo blanco y letras cantadas oscuras.
`fomo-xerox` añade textura de fotocopia; `--graphic-palette dark` invierte la paleta.
`--title-layout stacked|wide` permite hasta cuatro o dos filas, respectivamente.
El preset tiene prioridad sobre otros fondos y paletas del render y conserva la fuente de las letras cantadas.

`--graphic-style default` recupera la composición habitual. Para restaurar también fondo y
colores, elige otra configuración visual explícitamente. Solo `configure` guarda esas preferencias.

## Migrar trabajos antiguos

```bash
uv run karaoke migrate outputs --dry-run
uv run karaoke migrate outputs/JOB_ID --theme job
```

La migración actualiza `job.json`, normaliza logos y elimina `intro.logo`.
Usa `--theme job` para conservar deliberadamente un fondo estático; el modo `auto` lo cambia a aurora.
Conserva audio, letras y recursos. Reemplaza la configuración de forma atómica, sin historial de respaldos.
