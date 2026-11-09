# Diseño y render

[Volver al README](../README.md)

La configuración se hace con `karaoke configure PROYECTO`. Abre el menú por secciones
o pasa opciones explícitas. Solo **Guardar** escribe los cambios del menú; no genera
una previsualización. Consulta la [guía de configuración](project-cli.md).

Las mismas opciones en `render` afectan solo esa ejecución. Las opciones omitidas
conservan lo guardado; `configure` no cambia la tipografía ni el fondo por sí solo.
Los proyectos nuevos empiezan con letras Plus y fondo fluido.

## Presets, tipografía y color

```bash
uv run karaoke configure outputs/PROYECTO --preset fluid
uv run karaoke configure outputs/PROYECTO --preset cosmic
uv run karaoke configure outputs/PROYECTO --preset classic
uv run karaoke configure outputs/PROYECTO --visual-style classic --font-size 64
uv run karaoke configure outputs/PROYECTO --lyrics-active-color '#FFD34D' --lyrics-inactive-color '#E8E8E8'
```

`fluid` y `cosmic` usan palabras animadas con fondos fluido y de partículas,
respectivamente. `classic` selecciona subtítulos clásicos y fondo sólido.
`--visual-style plus|classic` cambia la tipografía sin elegir un fondo nuevo.

Plus usa Switzer Semibold y Braccato: karaoke desplaza frases y lyrics usa páginas
fijas. El tratamiento del texto inactivo difiere entre ambos modos. Switzer se descarga
con su licencia en `~/.cache/karaoke/fonts/`; Braccato está incluido con su
[licencia y procedencia](../src/karaoke_app/assets/braccato/PROVENANCE.json).

## Fondo y paleta

```bash
uv run karaoke configure outputs/PROYECTO --background-style fluid --theme forest
uv run karaoke configure outputs/PROYECTO --background-style cosmic-sand --seed 42
uv run karaoke configure outputs/PROYECTO --background-style fluid --cover portada.jpg
uv run karaoke configure outputs/PROYECTO --background-color '#112233'
uv run karaoke configure outputs/PROYECTO --background-image outputs/PROYECTO/fondo.jpg
uv run karaoke configure outputs/PROYECTO --background-video outputs/PROYECTO/fondo.mp4 \
  --background-crop-right 0.12 --background-overlay-opacity 0.25
```

Elige un solo tipo de fondo por comando. Las imágenes y videos de fondo deben estar dentro de
la carpeta del proyecto; la portada que aporta la paleta puede ser externa. En el menú,
las rutas relativas se interpretan desde el proyecto. En las opciones de línea de
comandos, las rutas relativas parten del directorio actual.

`--theme aurora|sunset|synthwave|stellar|forest|random` selecciona una paleta procedural.
`random` elige tema y semilla; los valores efectivos quedan en `render-settings.json`.
`--theme job`, el valor predeterminado, conserva el fondo guardado. Usa un tema concreto
y `--seed N` para repetir una combinación.

`--background-crop-right` elimina entre 0 y 0.5 del ancho de una imagen o video antes
de ajustarlo al lienzo. `--background-overlay-opacity` oscurece imágenes, videos o
fondos procedurales entre 0 y 1. El video de fondo se repite y su audio se ignora;
prepara un bucle continuo para evitar saltos. Se decodifica un fotograma antes de
guardar para rechazar archivos inválidos o que solo contienen audio.

## Título, intro y miniaturas

```bash
uv run karaoke configure outputs/PROYECTO --title "Mi canción" --artist "Artista" --align center
uv run karaoke configure outputs/PROYECTO --intro --intro-start 0.5 --intro-duration 3
uv run karaoke configure outputs/PROYECTO --intro-start 0.5 --intro-end 3.5
uv run karaoke configure outputs/PROYECTO --no-intro
uv run karaoke configure outputs/PROYECTO --thumbnail-time 3 --thumbnail-align end
uv run karaoke thumbnail outputs/PROYECTO --mode lyrics --align end
uv run karaoke intro outputs/PROYECTO --mode lyrics
```

`render` genera miniaturas y las intros habilitadas. La intro dura hasta cinco segundos
por defecto y termina antes de la primera voz; si no hay espacio, se omite. Desactivarla
no desactiva las miniaturas. `--intro-start` establece el comienzo; elige una duración
o un final absoluto, no ambos en el mismo comando. Guardar una duración sustituye
el final anterior y viceversa. La primera voz sigue limitando la intro.

`--align start|center|end` alinea título y artista, no las letras cantadas.
`--thumbnail-time` selecciona el instante del fondo de la miniatura; el valor inicial
es cero. Para un video, debe quedar antes de su final. `--thumbnail-align` permite
alinear la miniatura sin cambiar la intro. Las miniaturas y tarjetas locales no necesitan Colab. Repetir sus comandos
reemplaza los PNG correspondientes; usa `thumbnail --output-dir` para conservar variantes.

## Logo

```bash
uv run karaoke configure outputs/PROYECTO --logo logos/banner.png --logo-position top_left
uv run karaoke configure outputs/PROYECTO --logo-scale 0.18 --logo-opacity 0.85
uv run karaoke configure outputs/PROYECTO --no-logo
```

Las posiciones son `top_left`, `top_right`, `bottom_left` y `bottom_right`. La escala
va de 0.01 a 0.5 del ancho del video y la opacidad de 0 a 1. Conserva el archivo de logo
que utiliza el proyecto. La intro es transparente y no incorpora la marca de agua.

## Gráficos de cartel y fotocopia

```bash
uv run karaoke configure outputs/PROYECTO --graphic-style fomo --title-layout wide --align center
uv run karaoke configure outputs/PROYECTO --graphic-style fomo-xerox --graphic-palette dark
```

`fomo` y `fomo-xerox` son nombres de estilos de cartel reutilizables, no configuraciones
reservadas para una canción. Usan Abril Fatface, composición monocromática y, en Xerox,
textura de fotocopia. `--graphic-palette dark` invierte la paleta.

`--title-layout stacked|wide` permite hasta cuatro o dos filas. Estos estilos sustituyen
el fondo y la paleta, conservando la fuente de las letras cantadas.
`--graphic-style default` recupera la composición habitual; usa un preset para restaurar
también fondo y tipografía.

## Comandos locales existentes

El menú de configuración no incluye preview. Si necesitas usar los comandos locales
ya existentes, instala Chromium para `preview` y consulta sus límites:

```bash
uv run playwright install --with-deps chromium
uv run karaoke preview --help
uv run karaoke background --help
```

`preview` muestra letras y un fondo procedural sin la intro ni la marca del render final.
`background` dibuja solo un fondo procedural y acepta un directorio de proyecto o la
configuración independiente [cosmic-background.json](../examples/cosmic-background.json).
Ese archivo independiente no es el estado del proyecto ni configura sus renders.

## Proyectos antiguos

No hay migración automática ni comando `migrate`. Prepara un proyecto nuevo desde la
fuente original; los archivos antiguos permanecen intactos. Los ajustes actuales se
administran con la CLI, no mediante un archivo de configuración editable.
