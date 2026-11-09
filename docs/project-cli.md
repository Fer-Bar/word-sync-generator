# Configuración de proyectos

El flujo es **preparar → configurar → validar → renderizar**. No hay que abrir ni
editar un `job.json`. La aplicación conserva sus preferencias y referencias de
medios en un único archivo interno `.karaoke/project.json`. Guarda la carpeta
completa del proyecto para poder volver a renderizar.

```bash
uv run karaoke source cancion.wav --title "Canción" --artist "Artista" --preset fluid
uv run karaoke configure outputs/PROYECTO
uv run karaoke status outputs/PROYECTO
uv run karaoke validate outputs/PROYECTO
uv run karaoke render outputs/PROYECTO
```

## Menú por secciones

`configure PROYECTO` abre el menú cuando se ejecuta en una terminal. Se puede
entrar y volver a cualquier sección:

1. **Presets:** `fluid` (palabras animadas y fondo fluido), `cosmic` (partículas)
   o `classic` (subtítulos clásicos y fondo sólido).
2. **Tipografía:** palabras animadas o subtítulos clásicos, tamaño y colores de letras.
3. **Fondo:** fondo procedural, paleta, semilla, imagen, video o color sólido;
   recorte de imágenes/videos y opacidad de la capa oscura.
4. **Título y arte:** título, artista, gráficos, paleta, disposición, alineación y
   comienzo/duración/final de la intro; momento y alineación de la miniatura.
5. **Marca de agua:** elegir o desactivar el logo, posición, escala y opacidad.
6. **Video y salida:** resolución, FPS y modo karaoke, lyrics o ambos.

Los valores inválidos se explican sin perder las secciones ya elegidas. El resumen
compara lo guardado con la selección. Solo **Guardar** y su confirmación escriben
el estado. Cancelar o interrumpir deja todos los archivos del proyecto intactos.
No se genera una previsualización desde el menú.

Las imágenes y videos de fondo deben estar dentro de la carpeta del proyecto. Las rutas
relativas del menú se interpretan desde esa carpeta. El logo puede ser una imagen
externa; conserva ese archivo mientras lo use el proyecto.

## Uso sin preguntas

En scripts y notebooks se usan opciones explícitas:

```bash
uv run karaoke configure outputs/PROYECTO --preset cosmic --resolution 720p --fps 30 --mode lyrics
uv run karaoke configure outputs/PROYECTO --title "Otro título" --artist "Artista"
uv run karaoke configure outputs/PROYECTO --background-color '#112233' --no-logo
uv run karaoke configure outputs/PROYECTO --font-size 64 --lyrics-active-color '#FFFFFF' --no-intro
uv run karaoke configure outputs/PROYECTO --background-video outputs/PROYECTO/fondo.mp4 \
  --background-crop-right 0.1 --background-overlay-opacity 0.2
uv run karaoke configure outputs/PROYECTO --intro-start 0.5 --intro-end 3 --thumbnail-align end
```

Las opciones explícitas prevalecen sobre el preset. Las opciones omitidas conservan
lo guardado. Un preset modifica la apariencia, no el título, los medios ni la salida.
`configure` sin opciones en un proceso sin terminal falla con una indicación de
usar opciones explícitas, en vez de bloquearse esperando respuestas.

`render` permite las mismas opciones de apariencia solo para esa ejecución. Para
conservarlas se usa `configure`. Si se omite `render --mode`, se usa el modo guardado
(el valor inicial es `both`).

## Revisar antes de iniciar Colab

`status` muestra los ajustes guardados, disponibilidad de medios y videos exportados.
`validate` verifica ajustes, archivos necesarios para el modo seleccionado y letras
con tiempos por palabra. No sube archivos ni inicia Colab:

```bash
uv run karaoke validate outputs/PROYECTO --mode lyrics
uv run karaoke configure outputs/PROYECTO --preset classic --dry-run
```

La validación previa no descarga modelos ni comprueba autenticación, cuotas de GPU
u otros servicios remotos. Esos errores siguen reportándose al ejecutar el trabajo.

## Formato actual

Solo se aceptan proyectos preparados con el formato actual. Se eliminó el comando
`migrate` y la conversión implícita de esquemas antiguos. Para una carpeta con
`job.json` se prepara un proyecto nuevo desde la fuente original. No se borran ni
modifican automáticamente los archivos antiguos.
