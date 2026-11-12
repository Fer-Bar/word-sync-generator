# Generar videos desde Google Colab

[Volver al README](../README.md)

## Para quien usa el cuaderno

Abre [generate_video.ipynb](../notebooks/generate_video.ipynb) en Colab y selecciona
**Entorno de ejecución → Cambiar tipo de entorno de ejecución → T4 GPU**.
`notebooks/` es la única carpeta de entrega: contiene el cuaderno editable y su wheel.
El motor de una versión publicada se descarga automáticamente. Si la entrega local aún
no está publicada, el paso 1 pide subir el wheel de esa misma carpeta. Nunca instala una
versión anterior como sustituto: comprueba versión, SHA-256 y capacidades del motor.

1. **Iniciar:** elige **Modelo** (`small`, `medium` o `large-v3`, predeterminado).
   Descarga el `.whl` de GitHub Releases, verifica su SHA-256,
   instala el motor y comprueba la GPU. Un checksum incorrecto detiene el paso.
2. **Subir canción:** el bloque de texto común presenta las dos alternativas: ejecuta
   **2a o 2b**, no ambos. Cada celda contiene solo su propia entrada.
   En **2a**, pulsa ▶ para mostrar el
   botón nativo y subir el archivo local. En **2b**, pega el enlace antes de ▶;
   YouTube descarga un MP4 de hasta 720p con audio y metadatos.
   Espera **Archivo listo**. La celda permanece activa durante la transferencia.
   Volver a ejecutarla inicia una selección nueva y descarta los datos de la canción anterior.
3. **Datos de la canción:** ejecuta la celda para leer los metadatos, detectar el idioma
   y mostrar el formulario. Usa el mismo modelo elegido al iniciar; sus pesos se descargan
   aquí la primera vez, sin añadir un modelo pequeño. Compara fragmentos separados con voz;
   si la evidencia es débil, contradictoria o de un idioma no admitido, pide selección manual.
   El detector puede omitir voz cantada: no se presenta como una identificación infalible.
   Se ofrecen español, inglés, portugués, francés, italiano y alemán, compatibles con la cadena
   actual de transcripción y alineación. Siempre puedes corregir la sugerencia y volver a ejecutar
   el paso 3 no sobrescribe tu selección manual. Un fallo de detección tampoco impide editarla.
   Confirma título, artista e idioma. Título, artista y álbum se sugieren desde las
   etiquetas del archivo cuando existen; tus correcciones manuales se conservan.
   El álbum y el TXT son opcionales.
   **Subir letra TXT** permite aportar una letra propia. Al recibirla aparecen nombre,
   tamaño y las acciones **Cambiar TXT** y **Quitar**. Sin archivo, se busca la letra
   automáticamente; con archivo, no se consulta a los proveedores. No hay casilla de búsqueda.
4. **Crear voces y letra sincronizada:** valida el archivo y prepara voces, instrumental
   y letra con tiempos. Reutiliza los pesos de Whisper descargados en el paso 3;
   otros modelos pueden descargarse aquí. Todavía no genera vídeos.
   Respeta el idioma final del formulario. Para cambiar el modelo, vuelve al paso 1
   y selecciona de nuevo la canción; no hay un segundo selector en el paso 4.
   El proceso siempre analiza el audio con Whisper y alinea el texto conocido con CTC,
   también cuando LRCLIB aporta word sync. La letra y su estructura son la referencia;
   los tiempos finales se calculan sobre tu audio. La comprobación acústica ya no es opcional
   y se elimina la casilla **Verificar_tiempos**. Al terminar informa del motor utilizado y
   de los tiempos estimados o problemas pendientes. El render de un proyecto ya preparado
   utiliza el YAML actual sin volver a alinear. La separación de audio se mantiene.
   La revisión opcional **4b** se recorre de arriba abajo: **4b.1** descarga voces,
   **4b.2** descarga YAML, **4b.3** enlaza a LyricsEditor y explica qué abrir/exportar,
   y **4b.4** recibe el YAML corregido. Espera **YAML actualizado** al importarlo.
   Puedes omitir la sección completa y continuar con la letra actual.
   En **4c.1 · Elegir fondo**, pulsa ▶ para abrir el diseño guardado y después elige una opción: Clásico, Fluido,
   Cósmico, Color, Imagen, Vídeo o Vídeo de origen. No hay dos selectores que puedan
   contradecirse. Los tres fondos predefinidos tienen una muestra generada por el motor;
   se oculta al elegir un archivo o color. No simula la letra ni el movimiento.
   El fondo de color ofrece siete opciones con muestra visual y un selector personalizado.
   Solo aparecen los campos correspondientes al tipo de fondo elegido.
   En **4c.2 · Aplicar diseño**, pulsa ▶ y sube la imagen/vídeo si se solicita. Los archivos
   se validan y guardan en el proyecto; los clips cortos se repiten sin sustituir el audio.
   Espera **Diseño aplicado**. Cambiar cualquier valor exige aplicarlo de nuevo; el render
   rechaza cambios pendientes en vez de usar silenciosamente una selección anterior.
   Abrir los controles sin cambiar valores no exige 4c.2 ni descarta el vídeo anterior;
   volver a los valores guardados elimina el estado pendiente.
   Elegir Clásico, Fluido o Cósmico recupera ese fondo predefinido. Los fondos personalizados
   usan la tipografía clásica; no heredan una selección oculta anterior.
   Omitir 4c conserva el aspecto guardado del proyecto, sin forzar otro preset durante el render.
5. **Generar el vídeo:** elige **Lyrics**, **Karaoke** o **Ambos**, y la calidad. Usa la letra actual sin una casilla
   adicional de confirmación. Cambiar el aspecto no repite la preparación.
6. **Descargar:** MP4 está seleccionado por defecto. Guarda también el proyecto editable
   si quieres conservarlo antes de cerrar Colab.

Las celdas 4b usan la transferencia nativa de Colab, sin botones `ipywidgets` ni menú de acciones.
Permite descargar `vocals.flac` y `lyrics.lyricsfile.yaml` individualmente, sin repetir el paso 4.
El YAML corregido se valida antes de reemplazar la letra; se conserva una copia anterior
en el proyecto. Importarlo no repite la separación ni la transcripción. El ZIP editable
se crea al descargarlo para incluir la versión actual, sin los renders ni diagnósticos.

No hace falta editar rutas ni montar Google Drive. El audio se procesa
en la sesión de tu cuenta. Sin TXT, la búsqueda automática consulta proveedores externos;
con TXT, se usa ese archivo. Los modelos pueden necesitar Internet también al usar TXT.
Usa audio autorizado. La CLI conserva la semántica de sus flags.
Los formularios nativos (`@param`) se editan **antes de ejecutar su celda**; no aplican
cambios automáticamente. El botón de subida (`files.upload`) aparece **al ejecutar** y
espera la transferencia. Los paneles del paso 3 y 4c.1 se editan **después de ejecutar**.
No uses «Ejecutar todas»: hay rutas alternativas y subidas opcionales.
Al cambiar archivos o datos se conserva el último proyecto y vídeo completos.
El render queda bloqueado si los datos actuales no corresponden a esa preparación:
revierte los cambios o ejecuta el paso 4. Corregir título o artista puede cambiar la búsqueda
de letras, por lo que no se considera automáticamente un cambio solo visual.
Un intento fallido no sustituye los resultados anteriores, y un formulario antiguo no
invalida la canción activa. Para otra canción, reemplaza el audio y revisa metadatos
y TXT; los proyectos anteriores siguen disponibles para exportar. El formulario usa `ipywidgets`
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
YouTube se adquiere con el mismo servicio que la CLI. Si solicita autenticación, marca
**Subir_cookies** y ejecuta de nuevo **2b**: aparecerá el botón nativo para subir un archivo
Netscape. Espera **Cookies recibidas** y después **Archivo listo**. Se intenta primero sin
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

El cuaderno fija una versión y el SHA-256 exacto del wheel, no una rama mutable ni `latest`.
El repositorio público distribuye el wheel y ese mismo cuaderno juntos en GitHub Releases.
No hace falta mantener un archivo de checksum aparte. El hash detecta mezclas de entregas
y descargas alteradas o incompletas; no es una firma independiente.

Edita únicamente `notebooks/generate_video.ipynb`. Para regenerar su motor desde
`src/karaoke_app/` y `colab/`, usa `uv run python scripts/build_notebook.py`.
El comando construye en un directorio temporal, valida el contenido y deja un único wheel
en `notebooks/`, con versión y SHA-256 actualizados en el cuaderno. `--check` detecta un
wheel desactualizado respecto al código local o mezclado con otro cuaderno.

### Publicar una versión

Tras revisar los cambios, ejecutar los checks y autorizar la publicación:

1. Actualiza la versión en `pyproject.toml`, sin reutilizar una ya publicada.
2. Ejecuta `uv run python scripts/build_notebook.py` y luego el mismo comando con `--check`.
   `uv` actualiza el lockfile; el constructor actualiza la versión y el hash del cuaderno.
3. Confirma el código, el lockfile y el cuaderno de esa misma revisión.
4. Crea y publica el tag correspondiente a la versión del paquete.

El workflow `.github/workflows/release.yml` comprueba que tag, paquete y cuaderno
coincidan, verifica la exclusión de logos locales y ejecuta el mismo constructor. Rechaza
la publicación si reconstruir cambia el cuaderno confirmado en Git. Publica los dos
archivos de `notebooks/` mediante el token del propio workflow. **Publicar el tag activa la publicación**;
no se ejecuta por un push normal ni por abrir un PR. No requiere tokens en el cuaderno.
Si la release ya existe, falla en vez de reemplazar sus archivos silenciosamente.

Para inspeccionar el paquete localmente, sin publicar:

```bash
uv run python scripts/build_notebook.py --check
```

El wheel incluye módulos, scripts de runtime, recursos visuales genéricos y sus licencias. No
incluye logos personales, canciones, modelos, credenciales, Chromium ni FFmpeg del sistema. Switzer se
obtiene de Fontshare cuando se necesita; no se redistribuye dentro del wheel.
Los archivos de `logos/` permanecen locales e ignorados por Git, y solo se usan si se
seleccionan explícitamente. Retirarlos del árbol actual no los elimina del historial Git.

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

La caché de Whisper se conserva en `/content/karaoke-notebook/models`, fuera de las carpetas
de trabajo desechables y de los ZIP exportados. Detección y preparación usan el mismo modelo
y caché; cada proceso vuelve a cargar los pesos en memoria, pero no necesita descargarlos otra vez.
La caché no sobrevive a la eliminación del entorno de Colab.

Prefiere audio frente a un video grande: la preparación del notebook conserva la fuente
original en el proyecto. El ZIP editable contiene el proyecto preparado, no sus renders;
descarga también el paquete de videos si necesitas ambos.

## Verificación y límites

Referencias de interacción: [formularios de Colab](https://colab.research.google.com/notebooks/forms.ipynb)
y [código oficial de `files.upload`](https://github.com/googlecolab/colabtools/blob/main/google/colab/files.py).
`upload()` crea el input de archivo en la salida y bloquea hasta recibir los archivos.
La revisión de UX separa 2a/2b y las tres transferencias de 4b; 4c exige aplicar explícitamente
la selección. La comprobación sintáctica de estas celdas no sustituye su recorrido en navegador.

El panel visual toma como referencias los cuadernos oficiales de ipywidgets
[Widget List](https://github.com/jupyter-widgets/ipywidgets/blob/main/docs/source/examples/Widget%20List.ipynb)
y [Widget Styling](https://github.com/jupyter-widgets/ipywidgets/blob/main/docs/source/examples/Widget%20Styling.ipynb):
controles reales, `ColorPicker`, muestras HTML y contenedores que se adaptan al ancho.
Las muestras de estilos se calculan en el entorno del motor con `preparation_visuals`
y `background_frame`; no requieren otro wheel ni representan un render completo de la letra.

Se ejecutaron los widgets y el adaptador reales sobre una copia del proyecto de Jorja:
paleta, color personalizado, persistencia de configuración, retorno al fondo del preset y
bloqueo de render con cambios pendientes. El HTML embebido del panel se inspeccionó en
Chromium local a 1080 y 390 px, sin desbordamiento horizontal en la vista estrecha.
Esto verifica la presentación local; el recorrido interactivo dentro de Colab sigue pendiente.

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

**Sigue pendiente el recorrido completo de controles, reproducción y descargas dentro de Colab.**
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
`outputs/notebook-examples/youtube-backgrounds/`. Fue ejecución real por CLI, sin tests ni mocks;
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
