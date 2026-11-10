# Generar videos desde Google Colab

[Volver al README](../README.md)

## Para quien usa el cuaderno

Abre [generate_video.ipynb](../notebooks/generate_video.ipynb) en Colab y selecciona
**Entorno de ejecución → Cambiar tipo de entorno de ejecución → T4 GPU**.
Recibe del responsable el cuaderno y su paquete `.whl`; no construyas el paquete tú.

1. **Iniciar:** sube el `.whl`; se instala el motor y se comprueba la GPU.
2. **Tu canción:** ejecuta la celda para mostrar el formulario. Selecciona audio o vídeo
   y completa título, artista e idioma. El álbum y el TXT son opcionales.
   El TXT está en **Aportar mi letra · opcional**; los modelos y la búsqueda en
   **Opciones avanzadas**. La búsqueda automática está activada por defecto.
3. **Crear voces y letra sincronizada:** valida el archivo y prepara voces, instrumental
   y letra con tiempos. La primera vez descarga modelos; todavía no genera vídeos.
4. **Revisar la letra:** escucha la voz y comprueba texto, procedencia y tiempos por línea.
5. **Generar el vídeo:** elige modo, estilo y calidad. Usa la letra actual sin una casilla
   adicional de confirmación. Cambiar el aspecto no repite la preparación.
6. **Descargar:** guarda los vídeos y el proyecto editable antes de cerrar Colab.

Para corregir tiempos en [LyricsEditor](https://dotslashgabut.github.io/lyricseditor/),
el ZIP editable contiene `vocals.flac` y `lyrics.lyricsfile.yaml`. La importación del YAML
corregido en el formulario y el autocompletado de metadatos siguen pendientes; este cambio
prioriza el layout. No hay controles simulados para esas acciones.

No hace falta editar rutas ni usar tokens, cookies o Google Drive. El audio se procesa
en la sesión de tu cuenta; la búsqueda opcional de letras consulta proveedores externos.
Los modelos necesitan Internet incluso con esa búsqueda desactivada. Usa audio autorizado.
La letra TXT que subas tiene prioridad aunque desactives la búsqueda en línea; el
interruptor no significa «ignorar mi archivo». La CLI conserva la semántica de sus flags.
Los botones necesitan una sesión activa: aparecen al ejecutar **Tu canción**, no al
abrir un cuaderno sin ejecutar. Al cambiar archivos o datos se invalida la preparación
y revisión anterior. Para otra canción, reemplaza el audio y revisa también metadatos
y TXT; los proyectos ya generados permanecen en disco. El formulario usa `ipywidgets`
del entorno anfitrión de Colab; el motor conserva su entorno aislado.

### Probar el flujo real con una canción local

Usa un archivo propio o autorizado, con el título y artista de su versión exacta.
El notebook pide esos dos datos cuando vas a buscar letras automáticamente; no coloca
un título de ejemplo que pueda provocar una búsqueda incorrecta. El álbum es opcional.
El motor consulta LRCLIB y después Genius; si no hay una referencia válida, utiliza
transcripción. No se garantiza que un proveedor tenga la canción o esté disponible.

En el paso 4, «Origen de la letra» distingue proveedor, TXT y transcripción. Una
transcripción no demuestra que la búsqueda haya encontrado letras. Los tiempos se
muestran en minutos y segundos junto a cada línea. Un resultado
sin evidencia o con anclas insuficientes no se presenta como validado: escucha y revisa.

Después genera el video, comprueba audio/subtítulos en la previsualización y descarga
el MP4 y el proyecto editable. Repite solo el render si cambias el aspecto. La entrada
YouTube/cookies está pospuesta en el notebook, no eliminada de la CLI. No hay guardado
automático en Drive: descarga los archivos antes de desconectar el runtime.

El notebook está diseñado para la interfaz de **Google Colab**. No se presenta como una
interfaz comprobada para Kaggle o Jupyter genérico; las funciones Python del motor pueden
usarse desde otros entornos con sus dependencias disponibles.

## Distribuir el cuaderno sin compartir credenciales

El mantenedor construye el paquete desde una revisión concreta:

```bash
uv build --wheel
sha256sum dist/lyrics_generator-0.1.0-py3-none-any.whl
```

Entrega el wheel, su checksum, la revisión y el cuaderno correspondiente por el canal
privado acordado. El usuario final solo los sube. Un cambio del paquete requiere distribuir
el wheel nuevo junto con el cuaderno; no uses enlaces con tokens ni publiques el repositorio
o el paquete privado sin autorización. Ninguna celda descarga código de una rama mutable.

El wheel incluye módulos, scripts de runtime, recursos visuales y sus licencias. No
incluye canciones, modelos, credenciales, Chromium ni FFmpeg del sistema. Switzer se
obtiene de Fontshare cuando se necesita; no se redistribuye dentro del wheel.

## Un motor, dos interfaces

```text
CLI → sesiones y transferencias ─┐
                               ├→ preparación / rendering.py → runtime compartido
Notebook → notebook_runner.py ──┘
```

`rendering.prepare_render` valida opciones, audio y letras sin escribir. La CLI conserva
su `--dry-run` y gestión de sesiones. `rendering.render_subtitles` y `create_render_bundle`
producen los mismos subtítulos y recursos para ambas interfaces.

`notebook.prepare_audio` y `notebook.render_project` lanzan el runtime en procesos aislados.
`notebook_runner` adapta solicitudes JSON del cuaderno a esas funciones; no implementa
separación, alineación ni composición. El notebook muestra controles, reproduce resultados
y solicita descargas: no aprovisiona otra sesión de Colab.

## Entorno y archivos

El cuaderno utiliza `uv` para crear `/content/karaoke-env`, sin paquetes del sistema,
e instala allí el wheel y sus requisitos juntos. No reemplaza el Python ni las bibliotecas
GPU del proveedor. Esto también evita depender de `ensurepip`, ausente en la imagen probada.
La instalación comprueba dependencias; después el diagnóstico comprueba la GPU real.

Los requisitos fijan Torch 2.10 y TorchCodec 0.10, con bibliotecas CUDA 12 compatibles con
Faster Whisper. Se necesitan Python 3.12+, driver compatible con CUDA 12.8, FFmpeg/ffprobe
y las bibliotecas compartidas de FFmpeg. Reserva varios GB para bibliotecas y modelos.
La disponibilidad y cuota de GPU dependen de Colab.

Entradas y proyectos se guardan bajo `/content/karaoke-notebook`. Cada preparación y render
tiene un identificador distinto. Los renders quedan en `PROYECTO/renders/`; los fallos
conservan diagnósticos bajo `.runs/`. No borres esas rutas antes de revisar un error.
Todos estos archivos son temporales: descarga lo que necesites antes de cerrar la sesión.

Prefiere audio frente a un video grande: la preparación del notebook conserva la fuente
original en el proyecto. El ZIP editable contiene el proyecto preparado, no sus renders;
descarga también el paquete de videos si necesitas ambos.

## Verificación y límites

Las pruebas locales protegen servicios, contratos de CLI, archivos, cancelación y
recuperación. No se añade una batería de tests de celdas o controles del notebook.
Su verificación consiste en ejecutar el cuaderno y recorrer la interfaz del navegador.

En la sesión de comprobación se observaron Python 3.13.16 y Tesla T4; el entorno aislado
instaló los requisitos y cargó Demucs, Faster Whisper, CTC y TorchCodec. PyTorch
2.10.0+cu128 reconoció la GPU. Con una muestra de voz sintetizada de diez segundos se
completaron separación, transcripción y ambos renders: MP4 H.264/AAC, 1280×720, 24 fps,
240 fotogramas. Los hashes de las descargas por CLI coincidieron con los archivos remotos.
La repetición con el adaptador corregido confirmó la referencia TXT con búsqueda en línea
desactivada y la alineación CTC: texto suministrado y tiempos generados con procedencia
`ctc-forced-aligner`. Ambos videos se decodificaron completos y los resultados anteriores
conservaron sus hashes. La comprobación independiente de anclas ASR indicó anclas
insuficientes: no equivale a una validación completa de precisión temporal.

**Sigue pendiente el recorrido real de controles, reproducción y descargas en el navegador.**
La versión anterior del formulario se comprobó localmente con widgets reales: carga y
persistencia de ambos archivos, eliminación del TXT, rechazo de una extensión incorrecta,
limpieza del contenido del widget e invalidación al editar. También pasaron las 26 pruebas
de entradas y runtime y Ruff sobre el cuaderno. Esto no verifica el selector del navegador
ni la transferencia de archivos grandes en Colab.
El layout simplificado no tiene tests por petición del usuario: solo se comprueban la
estructura del notebook y la compilación de sus celdas. No se presenta como validación visual.
La ampliación de metadatos y revisión se comprueba localmente a través del adaptador del
motor; la búsqueda en línea con una canción real todavía requiere esa prueba en Colab.
No confundas un código de salida local de la CLI con éxito remoto.
Los procesos del notebook usan nivel INFO para no volcar trazas DEBUG de descarga de
modelos en las celdas. Revisa cualquier diagnóstico antes de compartirlo; puede contener
datos de entrada o enlaces temporales. La CLI mantiene su nivel de diagnóstico anterior.

Una prueba corta demuestra funcionamiento, no precisión para toda canción ni disponibilidad
garantizada. Revisa las letras y tiempos; conserva un resultado descargado para demostraciones.
