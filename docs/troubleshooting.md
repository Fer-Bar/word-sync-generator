# Acceso y recuperación

[Volver al README](../README.md)

## Credenciales

```bash
uv run colab sessions
```

La CLI utiliza `oauth2` por defecto; `--auth adc` permite seleccionar la alternativa.
Configura `HF_TOKEN` cuando las descargas de Hugging Face requieran autenticación.
Para Genius se admite `GENIUS_CLIENT_ACCESS_TOKEN` o `GENIUS_ACCESS_TOKEN`; no hacen falta
el client ID ni el client secret. `.env` no sobrescribe variables ya exportadas.
Consulta [.env.template](../.env.template).

`cookies.txt` es la ruta predeterminada para cookies Netscape de YouTube.
Usa `--cookies RUTA` para otra ubicación o `--no-cookies` para no utilizarlas.
No incluyas credenciales en commits ni resultados publicados.

## Errores al subir archivos

La CLI registra el tamaño de cada archivo y una estimación del payload base64
(aproximadamente un 33 % más grande, sin contar JSON). Antes de crear la sesión,
avisa si un paquete de preparación o render pesa al menos 64 MiB. Es un umbral
orientativo, no un límite confirmado de Colab; no bloquea la subida.

- **HTTP 413 / payload too large:** el servidor rechazó el tamaño de la petición.
- **HTTP 400:** la petición fue rechazada; el peso puede influir, pero ese código no confirma la causa.
- Otros errores conservan su diagnóstico sin atribuirlos al tamaño.

Si el paquete es grande, reduce el bitrate del fondo o usa audio comprimido sin pérdida
en lugar de WAV (por ejemplo, FLAC o WavPack, según el formato de muestras). Actualiza
la ruta correspondiente en `job.json` y conserva el original. Si también falla una subida
pequeña, revisa la sesión y el cliente Colab usando el error original del log.

## Límite de sesiones de Colab

Ante `HTTP 412 Precondition Failed` o `TooManyAssignmentsError`, comprueba tus sesiones y
cierra una que ya no necesites:

```bash
uv run colab sessions
uv run colab stop --session SESSION_NAME
```

Si aparece una asignación `[?]`, falta su estado local. Puedes liberar el runtime identificado
por el endpoint mostrado, sustituyendo `ENDPOINT`:

```bash
uv run python -c "from colab_cli.common import state; state.client.unassign('ENDPOINT')"
uv run colab sessions
```

## YouTube no descarga desde Colab

La CLI descarga ahora las URLs de YouTube localmente y sube el archivo a Colab.
Puedes seguir pasando la URL habitual. Ejecuta `uv sync` para instalar `yt-dlp` y
comprueba `deno --version`; si falta Deno, instálalo desde https://deno.com/.
La descarga prueba primero sin cookies y después con las cookies configuradas.
Un fallo local se muestra antes de crear el runtime; no garantiza resolver bloqueos
que YouTube también aplique a tu conexión local.

Si tienes el audio local, úsalo como entrada; se sube a Colab sin volver a descargarlo de YouTube:

```bash
uv run karaoke ./cancion.webm --title "Mi canción" --artist "Artista" --language es --no-cookies
```

Un rechazo desde Colab no demuestra por sí solo que las cookies hayan vencido.
El archivo local sigue necesitando separación y preparación de letras.

## Fallos de preparación

Al cancelar con `Ctrl+C`, el cliente intenta cerrar la sesión y conserva la interrupción.
Esto también se aplica si la creación de la sesión se interrumpe antes de recibir confirmación.
El manifiesto distingue `cancelled` de `failed` e incluye el error original.

`outputs/JOB_ID.recovery/recovery.json` registra sesión, errores, rutas remotas,
descargas y confirmación del cierre. Un fallo de letras puede dejar `checkpoint.zip`
con audio original, stems FLAC y diagnóstico. **No es un trabajo completo ni una reanudación**:
repetir el comando inicia otra preparación.

Si `session_stopped` es falso, usa la autenticación y sesión registradas para detenerla:

```bash
uv run colab --auth=AUTH stop --session SESSION_NAME
```

Los resultados que no pudieron descargarse no tienen recuperación garantizada.
Puedes borrar las carpetas `.recovery` cuando ya no necesites sus datos.

## Fallos de render

Las descargas de estado y resultados se reintentan hasta tres veces. Los archivos parciales
no se publican como resultados completos. Si falla la confirmación del cierre, el comando
termina con error e indica la sesión que debe cerrarse; los videos ya descargados permanecen
en `renders/`. El cierre usa un timeout de 60 segundos.

Los errores de dimensiones impares, fps fuera de 1–120 y timeout no positivo se detectan
antes de solicitar la sesión. Las dimensiones pares son necesarias para la salida H.264 usada
por el compositor.

## Dependencias remotas

| Error | Qué comprobar |
| --- | --- |
| `libcublas.so.12` no se encuentra | Ejecutar la preparación mediante el lanzador del proyecto, que configura las bibliotecas NVIDIA antes de iniciar Python. |
| `open() got an unexpected keyword argument 'metadata_errors'` | Usar las versiones de `colab/requirements.txt`; la configuración limita PyAV a `>=11,<19` para Faster Whisper 1.2.1. |
| `No module named 'karaoke_app'` en Colab | Actualizar juntos CLI, lanzador y servicios enviados: Colab recibe módulos independientes, no una instalación local del paquete. |

Repetir el comando con el código y las dependencias corregidos inicia una sesión nueva;
no reanuda automáticamente un checkpoint.
