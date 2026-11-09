# Notebook y paquete portable

[Volver al README](../README.md)

## Dos formas de preparar

- **CLI local:** adquiere el audio, abre una sesión Colab, transfiere archivos y descarga el proyecto.
- **Notebook:** ejecuta el mismo pipeline en el runtime que ya abriste. No usa Colab CLI,
  no abre otra sesión y no necesita cookies ni credenciales de Colab. Empieza con un archivo local.
  Usa el pipeline del paquete instalado, sin un ZIP de transferencia ni remapear sus rutas locales.

El notebook prepara audio separado y letras, no el video. Después descarga el ZIP,
extrae el proyecto, revisa la letra y usa `karaoke configure` y `karaoke render` desde la CLI.
No cambies manualmente el estado interno del proyecto.

## Abrir el notebook

Abre [prepare_audio.ipynb](../notebooks/prepare_audio.ipynb) en Jupyter, impórtalo en Colab
o súbelo a Kaggle. Selecciona GPU NVIDIA, acceso a Internet y Python 3.12 o posterior.
No todas las imágenes del proveedor cumplen estos requisitos. No reemplaces el Python del
sistema para forzar compatibilidad; elige otra imagen o usa la CLI.

1. El repositorio es privado: construye un wheel con `uv build` desde una revisión revisada
   en una máquina donde ya tengas acceso. Sube `dist/lyrics_generator-0.1.0-py3-none-any.whl`
   mediante Archivos en Colab o una entrada privada en Kaggle. Configura `WHEEL_PATH`.
   El notebook instala ese archivo y sus requisitos incluidos en una sola resolución,
   sin acceder al repositorio privado ni pedir tokens. Después ejecuta `pip check`.
   Usa un runtime limpio; si hay conflictos, no continúes hasta resolverlos.
2. Comprueba FFmpeg, ffprobe, paquetes del modelo y `nvidia-smi` con la celda de diagnóstico.
3. Sube un archivo propio o autorizado mediante Archivos en Colab, o una entrada privada
   en Kaggle. Configura su ruta, título, artista, idioma y, si tienes, una letra TXT revisada.
4. Ejecuta la preparación. Descarga el ZIP mostrado antes de cerrar el runtime.
5. Cierra el runtime desde la interfaz del proveedor para no seguir consumiendo cuota.

Los requisitos fijan Torch 2.10 y TorchCodec 0.10 según su
[matriz de compatibilidad](https://github.com/meta-pytorch/torchcodec#compatibility-with-torch-versions),
con las bibliotecas CUDA 12 que necesita Faster Whisper. TorchCodec requiere bibliotecas
compartidas de FFmpeg 4–8; el binario aislado de `imageio-ffmpeg` no las sustituye.
La GPU/driver debe soportar CUDA 12.8;
no se garantiza compatibilidad con GPUs antiguas como P100. Si el runtime ya trae cuDNN 13,
la instalación se detiene: sus archivos se solapan con cuDNN 12 y `pip check` no lo detecta.
Elige una imagen compatible o un entorno aislado; no se desinstalan paquetes del proveedor.
Reserva varios GB para bibliotecas y temporales; los modelos se descargan después.

En Kaggle la entrada puede ser de solo lectura: las salidas van a `/kaggle/working/karaoke`.
En Colab se usa `karaoke-output` dentro del directorio actual. Cada intento tiene un identificador
propio. Un fallo conserva diagnósticos/checkpoints bajo `.runs/`; no repitas la instalación
ni borres esa carpeta antes de revisar la causa. La descarga final está fuera de `.runs/`
para que puedas encontrarla en el panel de archivos.

`USE_LRCLIB` habilita búsqueda de referencias externas. Desactívalo para transcribir sin buscar
letras; los pesos de los modelos siguen necesitando Internet. No compartas un notebook con
rutas, títulos o salidas que no quieras publicar. No pegues secretos en sus celdas.

## Tamaño del audio de entrada

Prefiere un archivo de audio como FLAC. El notebook todavía no aplica la preparación
`audio-only` de la CLI antes de invocar el pipeline: si eliges un video local, el proyecto
y su ZIP pueden conservar ese video completo como fuente original. La optimización de
transferencias de la CLI no implica que esté aplicada a este frontend.

## Instalar sin checkout

Con Python 3.12+ y acceso previo al checkout privado, selecciona la revisión que quieres
usar y construye el paquete. Instala o transfiere el wheel a otro entorno; no necesitas
copiar credenciales de GitHub ni conservar el checkout junto al ejecutable.

```bash
uv build
python -m pip install dist/lyrics_generator-0.1.0-py3-none-any.whl
karaoke --help
```

Para el notebook, usa las celdas de instalación en lugar del segundo comando: resuelven
el wheel y los requisitos de modelos juntos. Mantén privados tanto el wheel como la
entrada de Kaggle. No uses enlaces con tokens ni publiques el paquete privado.

El wheel incluye scripts del pipeline, dependencias remotas declaradas, logos, fuentes y
recursos del renderer. No incluye modelos, Chromium, FFmpeg del sistema ni credenciales.
Los scripts y logos se leen del paquete; `outputs/`, `.env`, cookies, logos personalizados
y registros se escriben/buscan en el directorio actual, nunca en `site-packages`.
Desde un checkout se conserva la raíz del repositorio como directorio de trabajo predeterminado.

## Qué se verificó y qué falta

Una prueba de integración recorre configuración real, lectura de audio/metadata y decodificación
con FFmpeg hasta la frontera de separación GPU. Solo se reemplaza esa frontera; no se simulan
configuración, desempaquetado, adquisición ni decodificación. Otra prueba lanza el pipeline real
en un subproceso sin bundle y verifica un error de entrada conocido antes de inferencia.

Las pruebas locales cubren configuración sin efectos secundarios, archivos de entrada fuera
del directorio de salida, intentos aislados, errores/checkpoints, rutas del runtime y extracción
segura del ZIP. El lanzador se ejecuta en un proceso real con dependencias CUDA simuladas.
Las celdas se comprueban sintácticamente y se ejecuta un smoke test local sin
GPU ni descarga de modelos. Las celdas de instalación se prueban aparte en un entorno Python 3.12
vacío, sin tokens ni acceso al repositorio privado, seguido de `pip check` e imports reales.
TorchCodec decodificó un WAV sintético de 4000 muestras a 16 kHz sin diferencias de muestras;
esa comprobación valida ABI/FFmpeg en CPU, no inferencia GPU. Se construye e instala el wheel fuera del checkout para comprobar sus recursos.

**No se ejecutó inferencia completa en una cuenta real de Colab o Kaggle.** No están comprobadas
sus cuotas, autenticación, compatibilidad de imágenes/modelos ni calidad acústica. La lista de
prerrequisitos y el smoke test no equivalen a una validación de esas plataformas.
