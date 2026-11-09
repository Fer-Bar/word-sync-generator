# Diseño y render

[Volver al README](../README.md)

## Configurar un proyecto

```bash
uv run karaoke configure outputs/JOB_ID
uv run karaoke status outputs/JOB_ID
uv run karaoke validate outputs/JOB_ID
```

El menú organiza metadatos, salida, apariencia, fondo y marca de agua por secciones.
Enter conserva el valor actual; cancelar no guarda. `configure` persiste las preferencias
de forma atómica sin modificar audio ni letras. Los flags de `render` solo afectan esa
corrida. No edites el estado interno del proyecto. [Flujo y opciones de la CLI](project-cli.md).

También puedes usar flags para scripts:

```bash
uv run karaoke configure outputs/JOB_ID --preset fluid --cover portada.jpg
uv run karaoke configure outputs/JOB_ID --title "Mi canción" --artist "Artista" --resolution 720p --fps 24
uv run karaoke render outputs/JOB_ID --mode both
```

Presets: `fluid`, `cosmic` y `classic`. `--visual-style plus|classic` selecciona las letras;
`--background-style fluid|cosmic-sand` selecciona el fondo procedural. `--cover` toma colores
de una imagen. No combines fondo procedural con `--background-image` o `--background-color`.

Plus usa Switzer Semibold y resaltado por palabra. Karaoke desplaza frases y lyrics muestra
páginas fijas. Switzer se descarga con su licencia en `~/.cache/karaoke/fonts/`.
Braccato conserva su [licencia y procedencia](../src/karaoke_app/assets/braccato/PROVENANCE.json).

## Paletas y fondos

```bash
uv run karaoke render outputs/JOB_ID --theme forest --background-style fluid
uv run karaoke configure outputs/JOB_ID --background-color '#0B1020'
uv run karaoke configure outputs/JOB_ID --background-image outputs/JOB_ID/portada.jpg
```

Copia una imagen propia dentro del proyecto antes de seleccionarla. `--theme job`, el valor
predeterminado, conserva el fondo guardado. Las paletas `aurora`, `sunset`, `synthwave`,
`stellar` y `forest` cambian los colores del render. `forest` usa verdes oscuros sobre una
base casi negra. `random` guarda la elección en `render-settings.json`; usa la paleta elegida
y `--seed N` para repetirla. No cambies archivos internos para ajustar colores.

## Previsualizar

Instala Chromium una vez y prueba un fragmento corto:

```bash
uv run playwright install --with-deps chromium
uv run karaoke preview outputs/JOB_ID --mode karaoke --start 15 --duration 8 --output preview.mp4
uv run karaoke background examples/cosmic-background.json --output cosmic-preview.mp4
```

`preview` usa instrumental en karaoke y audio original en lyrics. Genera MP4, ASS y JSON,
sin sobrescribir salidas existentes. Muestra letras y fondo, pero no intro ni marca de agua.
Para fondos estáticos, selecciona un procedural con `--background-style` al previsualizar.

`background` genera solo el fondo. Acepta un proyecto o una configuración independiente como
[cosmic-background.json](../examples/cosmic-background.json), sin editar el estado del proyecto.
Admite `--start`, `--duration`, `--width`, `--height` y `--fps` para vistas rápidas.
La generación del fondo usa CPU; un fragmento recortado no necesariamente cierra el bucle.

## Miniaturas, intro y logo

```bash
uv run karaoke render outputs/JOB_ID --logo logos/banner.png --logo-position top_left
uv run karaoke thumbnail outputs/JOB_ID --mode lyrics --align end
uv run karaoke thumbnail --title "Mi canción" --artist "Artista" --output-dir outputs/miniaturas
uv run karaoke intro outputs/JOB_ID --mode lyrics
```

El render genera miniaturas y una intro cuando hay espacio antes de la primera voz.
El título y artista se cambian desde `configure`. `--align start|center|end` alinea esos
textos, no las letras cantadas. `--no-logo` desactiva la marca. Los logos se reutilizan
desde `logos/`, sin escribir dentro del paquete instalado.

`thumbnail` e `intro` son locales y no abren Colab. Repetir una miniatura puede reemplazar
sus PNG; usa `--output-dir` para variantes. El render conserva sus artefactos en una carpeta
propia dentro de `renders/`, incluidos miniaturas, intro habilitada y configuración efectiva.

## FOMO y fotocopia

```bash
uv run karaoke configure outputs/JOB_ID --graphic-style fomo --title-layout wide --align center
uv run karaoke configure outputs/JOB_ID --graphic-style fomo-xerox --graphic-palette dark
uv run karaoke render outputs/JOB_ID --mode lyrics
```

FOMO usa Abril Fatface para título y artista, fondo blanco y letras oscuras. `fomo-xerox`
añade textura; `--graphic-palette dark` invierte la paleta. `--title-layout stacked|wide`
permite hasta cuatro o dos filas. La composición gráfica tiene prioridad sobre fondo y
paleta, pero conserva la fuente de las letras cantadas.

`--graphic-style default` recupera la composición habitual. Para cambiar también fondo y
colores, selecciona otras opciones explícitamente. Solo `configure` guarda preferencias.

## Proyectos antiguos

No hay comando de migración ni compatibilidad con el estado anterior. Conserva los archivos
originales y prepara un proyecto nuevo con `karaoke source`.
