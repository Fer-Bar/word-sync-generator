# Notebook y paquete portable

[Volver al README](../README.md)

## Dos formas de preparar

- **CLI local:** adquiere el audio, abre una sesión Colab, transfiere archivos y descarga el proyecto.
- **Notebook:** ejecuta el mismo pipeline en el runtime que ya abriste. No usa Colab CLI,
  no abre otra sesión y no necesita cookies ni credenciales de Colab. Empieza con un archivo local.

El notebook prepara audio separado y letras, no el video. Después descarga el ZIP,
extrae el proyecto, revisa la letra y usa `karaoke configure` y `karaoke render` desde la CLI.
No cambies manualmente el estado interno del proyecto.

## Abrir el notebook

Abre [prepare_audio.ipynb](../notebooks/prepare_audio.ipynb) en Jupyter, impórtalo en Colab
o súbelo a Kaggle. Selecciona GPU NVIDIA, acceso a Internet y Python 3.12 o posterior.
No todas las imágenes del proveedor cumplen estos requisitos. No reemplaces el Python del
sistema para forzar compatibilidad; elige otra imagen o usa la CLI.

1. Ejecuta configuración e instalación. Puedes fijar `REPOSITORY_REF` a un commit revisado.
   La referencia predeterminada es `main`; en una rama de desarrollo usa esa rama o su commit.
2. Comprueba FFmpeg, ffprobe, paquetes del modelo y `nvidia-smi` con la celda de diagnóstico.
3. Sube un archivo propio o autorizado mediante Archivos en Colab, o una entrada privada
   en Kaggle. Configura su ruta, título, artista, idioma y, si tienes, una letra TXT revisada.
4. Ejecuta la preparación. Descarga el ZIP mostrado antes de cerrar el runtime.
5. Cierra el runtime desde la interfaz del proveedor para no seguir consumiendo cuota.

En Kaggle la entrada puede ser de solo lectura: las salidas van a `/kaggle/working/karaoke`.
En Colab se usa `karaoke-output` dentro del directorio actual. Cada intento tiene un identificador
propio. Un fallo conserva diagnósticos/checkpoints bajo `.runs/`; no repitas la instalación
ni borres esa carpeta antes de revisar la causa. La descarga final está fuera de `.runs/`
para que puedas encontrarla en el panel de archivos.

`USE_LRCLIB` habilita búsqueda de referencias externas. Desactívalo para transcribir sin buscar
letras; los pesos de los modelos siguen necesitando Internet. No compartas un notebook con
rutas, títulos o salidas que no quieras publicar. No pegues secretos en sus celdas.

## Instalar sin checkout

Con Python 3.12+ y una revisión revisada del repositorio:

```bash
python -m pip install 'git+https://github.com/Fer-Bar/word-sync-generator.git@main'
karaoke --help
```

También puedes construir un wheel e instalar ese archivo en otro entorno:

```bash
uv build
python -m pip install dist/lyrics_generator-0.1.0-py3-none-any.whl
```

El wheel incluye scripts del pipeline, dependencias remotas declaradas, logos, fuentes y
recursos del renderer. No incluye modelos, Chromium, FFmpeg del sistema ni credenciales.
Los scripts y logos se leen del paquete; `outputs/`, `.env`, cookies, logos personalizados
y registros se escriben/buscan en el directorio actual, nunca en `site-packages`.
Desde un checkout se conserva la raíz del repositorio como directorio de trabajo predeterminado.

## Qué se verificó y qué falta

Las pruebas locales cubren configuración sin efectos secundarios, archivos de entrada fuera
del directorio de salida, intentos aislados, errores/checkpoints, rutas del runtime y extracción
segura del ZIP. El lanzador se ejecuta en un proceso real con dependencias CUDA simuladas.
Las celdas se comprueban sintácticamente y se ejecuta un smoke test local sin instalación,
GPU ni descarga. Se construye e instala el wheel fuera del checkout para comprobar sus recursos.

**No se ejecutó inferencia completa en una cuenta real de Colab o Kaggle.** No están comprobadas
sus cuotas, autenticación, compatibilidad de imágenes/modelos ni calidad acústica. La lista de
prerrequisitos y el smoke test no equivalen a una validación de esas plataformas.
