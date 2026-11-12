# Generar videos desde Google Colab

[Volver al README](../README.md)

## Para quien usa el cuaderno

Abre [generate_video.ipynb](../notebooks/generate_video.ipynb) en Colab y selecciona
**Entorno de ejecución → Cambiar tipo de entorno de ejecución → T4 GPU**.
Recibe del responsable el cuaderno y su paquete `.whl`; no construyas el paquete tú.

1. **Iniciar:** sube el `.whl`; se instala el motor y se comprueba la GPU.
2. **Elegir canción:** selecciona **Archivo local** o **YouTube**. Sube el archivo o pega
   el enlace y ejecuta la celda. YouTube descarga un MP4 de hasta 720p con audio y metadatos.
   Espera **Archivo listo**. La celda permanece activa durante la transferencia.
   Volver a ejecutarla inicia una selección nueva y descarta los datos de la canción anterior.
3. **Datos de la canción:** ejecuta la celda para leer los metadatos y mostrar el formulario.
   Confirma título, artista e idioma. Título, artista y álbum se sugieren desde las
   etiquetas del archivo cuando existen; tus correcciones manuales se conservan.
   El álbum y el TXT son opcionales.
   El TXT está en **Aportar mi letra · opcional**; la búsqueda automática está visible
   y activada por defecto. Estos controles no están ocultos en acordeones.
4. **Crear voces y letra sincronizada:** valida el archivo y prepara voces, instrumental
   y letra con tiempos. La primera vez descarga modelos; todavía no genera vídeos.
   Selecciona **Modelo** al iniciar el cuaderno: `small`, `medium` o `large-v3` (predeterminado).
   Detección y preparación reutilizan ese modelo y sus pesos descargados.
   La celda independiente **4b · Revisar en LyricsEditor (opcional)** muestra el enlace al editor.
   Elige **Descargar voces**, ejecútala, y repite con **Descargar letra**. Abre ambos archivos
   en LyricsEditor. Para aplicar cambios, elige **Importar YAML corregido** y sube el YAML
   exportado. Puedes omitir esta celda y continuar con la letra actual.
   **4c.1 · Elegir fondo** abre los controles con el diseño guardado. Clásico, Fluido y Cósmico
   tienen muestras; Color ofrece paleta y selector. Imagen, Vídeo y Vídeo de origen muestran
   únicamente sus ajustes. Abrir el panel sin editar no exige aplicarlo ni descarta el vídeo.
   **4c.2 · Aplicar diseño** guarda los cambios y solicita el archivo cuando corresponde.
   Los vídeos cortos se repiten sin sustituir la canción. Cambiar valores bloquea el render
   hasta aplicarlos; volver a los valores guardados elimina ese estado pendiente.
5. **Generar el vídeo:** elige **Lyrics**, **Karaoke** o **Ambos** y calidad. Usa la letra actual sin una casilla
   adicional de confirmación. Conserva el aspecto guardado, sin forzar otro preset.
   Cambiar el aspecto no repite la preparación.
6. **Descargar:** MP4 está seleccionado por defecto. Guarda también el proyecto editable
   si quieres conservarlo antes de cerrar Colab.

La celda 4b usa el formulario y la transferencia nativos de Colab, sin botones `ipywidgets`.
Permite descargar `vocals.flac` y `lyrics.lyricsfile.yaml` individualmente, sin repetir el paso 4.
El YAML corregido se valida antes de reemplazar la letra; se conserva una copia anterior
en el proyecto. Importarlo no repite la separación ni la transcripción. El ZIP editable
se crea al descargarlo para incluir la versión actual, sin los renders ni diagnósticos.

No hace falta editar rutas ni montar Google Drive. El audio se procesa
en la sesión de tu cuenta; la búsqueda opcional de letras consulta proveedores externos.
Los modelos necesitan Internet incluso con esa búsqueda desactivada. Usa audio autorizado.
La letra TXT que subas tiene prioridad aunque desactives la búsqueda en línea; el
interruptor no significa «ignorar mi archivo». La CLI conserva la semántica de sus flags.
Los controles necesitan una sesión activa: aparecen al ejecutar su celda, no al
abrir un cuaderno sin ejecutar. Cambiar archivos o datos conserva el último proyecto y vídeo;
el render exige revertir los cambios o preparar los nuevos datos. Para otra canción, reemplaza el audio y revisa también metadatos
y TXT; los proyectos ya generados permanecen en disco. El formulario usa `ipywidgets`
del entorno anfitrión de Colab; el motor conserva su entorno aislado.

### Probar el flujo real con una canción local

Usa un archivo propio o autorizado, con el título y artista de su versión exacta.
El notebook pide esos dos datos cuando vas a buscar letras automáticamente; no coloca
un título de ejemplo que pueda provocar una búsqueda incorrecta. El álbum es opcional.
El motor consulta LRCLIB y después Genius; si no hay una referencia válida, utiliza
transcripción. No se garantiza que un proveedor tenga la canción o esté disponible.

Al terminar el paso 4, «Origen de la letra» distingue proveedor, TXT y transcripción.
Una transcripción no demuestra que la búsqueda haya encontrado letras. La revisión de
texto y tiempos se realiza en LyricsEditor con las voces y el YAML descargados. Un resultado
sin evidencia o con anclas insuficientes sigue indicado como pendiente de revisión.

Después genera el video, comprueba audio/subtítulos en la previsualización y descarga
el MP4 y el proyecto editable. Repite solo el render si cambias el aspecto. La entrada
YouTube se adquiere con el mismo servicio que la CLI. Si solicita autenticación, selecciona
**Subir cookies.txt** y repite el paso 2 con un archivo Netscape. Se intenta primero sin
cookies; la copia temporal se usa solo para reintentar y no se incluye en el proyecto.
Las cookies subidas se eliminan al terminar el intento. La CLI conserva la descarga de
audio por defecto; el notebook solicita vídeo y reutiliza el audio para la preparación.
Los metadatos de YouTube son sugerencias editables; pueden faltar artista o álbum.
No hay guardado
automático en Drive: descarga los archivos antes de desconectar el runtime.

El notebook está diseñado para la interfaz de **Google Colab**. No se presenta como una
interfaz comprobada para Kaggle o Jupyter genérico; las funciones Python del motor pueden
usarse desde otros entornos con sus dependencias disponibles.

## Distribuir el cuaderno sin compartir credenciales

El mantenedor construye el paquete desde una revisión concreta:

```bash
uv build --wheel
sha256sum dist/lyrics_generator-0.1.1-py3-none-any.whl
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

### Preparación y señales de actividad

La instalación del paso 1 retransmite la salida de sus comandos. El motor del notebook
también solicita salida real de Demucs y de los instaladores del renderizador. Whisper
muestra la descarga de los modelos ofrecidos por el formulario y el progreso real de
transcripción. La carga de Whisper y del alineador indica el dispositivo seleccionado.
Se conserva INFO, sin activar DEBUG ni añadir avisos periódicos de actividad. El render
ya comunica el tiempo de vídeo codificado mediante eventos de FFmpeg.

Un aviso de Colab sobre GPU sin uso no demuestra un fallo: la disponibilidad de CUDA y
su utilización son cosas distintas. La causa de la ejecución reportada sin logs aún no
se ha reproducido en Colab. Si no aparece ni el mensaje inicial del motor, conserva la
salida de la celda, el wheel utilizado y la ruta de diagnóstico; no repitas preparaciones
simultáneas. Para cancelar, usa el botón de detener la celda; el adaptador mantiene la
terminación del grupo de procesos y conserva los archivos del intento.

### Ejecución real de la canción suministrada

La ampliación de YouTube y fondos se verificó también el 10 de noviembre de 2026 con
el wheel 0.1.1 en una T4 dedicada. YouTube rechazó la descarga anónima desde Colab; el
reintento con las cookies aportadas descargó «What's Done Is Done», de Jorja Smith,
con metadatos. La preparación real usó English/Whisper small y LRCLIB aportó 43 líneas.
La recuperación dejó tiempos `estimated` de `faster-whisper`, pendientes de revisión.

El adaptador compartido configuró y renderizó tres vídeos Lyrics/Clásico de 173,333 s,
H.264/AAC a 720p, con color, imagen y un clip de ocho segundos repetido como fondo.
Los tres se decodificaron completos; los hashes descargados coincidieron. El ZIP editable
conservó el fondo final y la letra actual, sin cookies ni metadatos privados del descargador.
Las cookies temporales se eliminaron y la sesión se cerró. Los archivos están en
`dist/results/youtube-backgrounds/`. Fue ejecución real por CLI, sin tests ni mocks;
la interacción de los selectores del navegador permanece como comprobación humana.

El 10 de noviembre de 2026 se ejecutó la canción completa «Ocean Eyes» (199,545 s) en
una Tesla T4, dentro del entorno aislado del notebook. Se leyeron título, artista y álbum;
LRCLIB aportó 34 líneas. Se usó Whisper `small` y el estilo Clásico a 720p en esta ejecución.
La preparación terminó en 102 s y Whisper y el alineador
indicaron CUDA. Los registros de separación, descarga de Whisper y transcripción
llegaron al mismo retransmisor de salida antes de terminar la preparación.

Con el wheel final también se completaron la importación del YAML descargado y vuelto
a subir, la exportación actualizada y el vídeo Lyrics H.264/AAC, 1280×720, 24 fps. El
vídeo se decodificó completo; los hashes de MP4, voces, YAML y proyecto descargados
coincidieron con los remotos, y el WAV original permaneció intacto. La sesión terminó.
No se ejecutaron tests: fue procesamiento real mediante la CLI de Colab.

La alineación indicó `needs_review: true`: hay que escuchar y corregir los tiempos cuando
sea necesario. No se observó la descarga del modelo Demucs, aunque sí su separación.
Esta ejecución no verificó los controles del navegador ni su entrega visual de logs;
la captura de evidencia de la CLI conservó una referencia a stdout entre ejecuciones,
por lo que sus llamadas posteriores no mostraron todo en pantalla. Los registros privados
con marcas de tiempo preservan la llegada de salida antes de la finalización. No se
añadió ese capturador al notebook distribuido. El modo Karaoke no se ejecutó en esta ronda.
La ampliación de metadatos y revisión se comprueba localmente a través del adaptador del
motor; la búsqueda en línea con una canción real todavía requiere esa prueba en Colab.
No confundas un código de salida local de la CLI con éxito remoto.
Los procesos del notebook usan nivel INFO para no volcar trazas DEBUG de descarga de
modelos en las celdas. Revisa cualquier diagnóstico antes de compartirlo; puede contener
datos de entrada o enlaces temporales. La CLI mantiene su nivel de diagnóstico anterior.

Una prueba corta demuestra funcionamiento, no precisión para toda canción ni disponibilidad
garantizada. Revisa las letras y tiempos; conserva un resultado descargado para demostraciones.

## Detección de idioma con el modelo seleccionado

Elige `small`, `medium` o `large-v3` en el paso 1. El paso 3 detecta el idioma antes
del formulario usando ese mismo modelo, sin descargar otro pequeño. Puedes corregir
el idioma; si no hay evidencia suficiente, debes seleccionarlo manualmente.
El paso 4 respeta tu selección y reutiliza los pesos guardados en
`/content/karaoke-notebook/models`, fuera de las carpetas de trabajo desechables.
Cada proceso carga sus pesos en memoria; la caché dura mientras exista la sesión.

Editar los datos no borra el último proyecto ni vídeo completos. Si ya no corresponden
a los datos actuales, revierte los cambios o repite el paso 4 antes de generar.
Un intento fallido conserva los resultados anteriores para descargarlos.
