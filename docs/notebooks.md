# Generar videos desde Google Colab

[Volver al README](../README.md)

## Para quien usa el cuaderno

Abre [generate_video.ipynb](../notebooks/generate_video.ipynb) en Colab y selecciona
**Entorno de ejecución → Cambiar tipo de entorno de ejecución → T4 GPU**.
Recibe del responsable el cuaderno y su paquete `.whl`; no construyas el paquete tú.

1. Ejecuta la instalación y selecciona el `.whl` recibido.
2. Comprueba la GPU con el diagnóstico del cuaderno.
3. Selecciona tu audio, completa título/artista/idioma y, opcionalmente, sube una letra `.txt`.
4. Espera a que termine la preparación. La primera ejecución descarga modelos.
5. Escucha la voz y lee las letras. Si hay errores, aporta una letra corregida y repite
   la preparación; activa «Cambiar letra» para sustituir una referencia anterior.
6. Confirma la revisión, elige modo/aspecto y genera el video. Cambiar el aspecto no repite
   la separación ni la transcripción. `classic` es la opción más sencilla para empezar.
7. Descarga el MP4 o el paquete ZIP. Conserva también el proyecto editable para usarlo
   después desde la CLI. Cierra el entorno desde Colab cuando hayas terminado.

No hace falta editar rutas ni usar tokens, cookies o Google Drive. El audio se procesa
en la sesión de tu cuenta; la búsqueda opcional de letras consulta proveedores externos.
Los modelos necesitan Internet incluso con esa búsqueda desactivada. Usa audio autorizado.
La letra TXT que subas tiene prioridad aunque desactives la búsqueda en línea; el
interruptor no significa «ignorar mi archivo». La CLI conserva la semántica de sus flags.

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
No confundas un código de salida local de la CLI con éxito remoto.
Los procesos del notebook usan nivel INFO para no volcar trazas DEBUG de descarga de
modelos en las celdas. Revisa cualquier diagnóstico antes de compartirlo; puede contener
datos de entrada o enlaces temporales. La CLI mantiene su nivel de diagnóstico anterior.

Una prueba corta demuestra funcionamiento, no precisión para toda canción ni disponibilidad
garantizada. Revisa las letras y tiempos; conserva un resultado descargado para demostraciones.
