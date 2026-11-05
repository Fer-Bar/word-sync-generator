# Desarrollo y medición

[Volver al README](../README.md)

## Entorno y comprobaciones

Usa Python 3.12 y `uv`. Instala o sincroniza dependencias cuando sea necesario:

```bash
uv sync --dev
source .venv/bin/activate
uv run ruff check .
uv run pytest
```

Las pruebas de integración visual necesitan Chromium:

```bash
uv run playwright install --with-deps chromium
uv run pytest tests/test_browser_lyrics.py tests/test_render_graphics_runtime.py -q
```

Las reglas de Ruff y las dependencias locales están en [pyproject.toml](../pyproject.toml).
Las dependencias remotas están en [colab/requirements.txt](../colab/requirements.txt).

La suite cubre composición real con FFmpeg y Chromium, además de fallos simulados de red,
cancelaciones y cierre de sesiones. Las pruebas de orquestación sustituyen los comandos Colab;
no necesitan una GPU remota. Las comprobaciones específicas de Switzer se omiten cuando la
fuente no está disponible en la caché local. No hacen falta pruebas nuevas para eliminar un
comentario redundante: reserva las regresiones para comportamientos y errores reproducibles.

## Organización

| Ruta | Responsabilidad |
| --- | --- |
| `src/karaoke_app/cli.py` | Comandos y coordinación de sesiones y artefactos. |
| `src/karaoke_app/` | Servicios de letras, configuración y render local. |
| `colab/karaoke_job.py` | Preparación y composición remotas. |
| `colab/karaoke_launch.py` | Entorno y lanzamiento del proceso remoto. |
| `src/karaoke_app/assets/` | Motor visual, fuentes y licencias. |
| `tests/` | Pruebas unitarias e integración. |

La instalación soportada actualmente es desde el checkout con `uv`; la CLI localiza los
scripts de `colab/` junto al repositorio. Un wheel independiente necesitaría empaquetar esos
recursos y cambiar su resolución. No debe anunciarse como una distribución autónoma todavía.

El workflow [Checks](../.github/workflows/checks.yml) instala el entorno con el lockfile,
comprueba Ruff, ejecuta la suite local y construye los paquetes. No accede a cuentas Colab,
credenciales ni canciones privadas. La validación acústica de modelos debe realizarse aparte
con audio autorizado y referencias revisadas.

## Rendimiento

Cada operación guarda `performance.json`. `client_elapsed_seconds` mide el flujo del cliente,
incluidas transferencias y cierre; `gpu_requested` indica la GPU solicitada, no la asignada.
Los tiempos de etapas concurrentes no se suman para obtener el total.

El render captura Braccato en Chromium y envía PNGs al compositor FFmpeg.
Reutiliza capturas vacías sin eliminar fotogramas. `draw_seconds`, `screenshot_seconds`,
`captured_frames` y `reused_blank_frames` permiten distinguir dibujo y captura;
`pipe_seconds` incluye espera por FFmpeg. NVENC se comprueba antes de usarse y tiene respaldo
libx264; si falla durante el render, la captura se reinicia desde el principio.

Para comparar cambios, utiliza la misma canción, resolución, fps, modo y hardware.
Distingue mediciones locales de Colab y separa inferencia, captura, empaquetado y transferencias.
Las pruebas con dobles de red o modelos GPU no miden velocidad ni precisión de inferencia real.
Guarda resultados de experimentos en reportes, sin convertirlos en instrucciones del README.

## Comparar alineaciones

El comparador no modifica los archivos de entrada:

```bash
uv run python -m karaoke_app.alignment_benchmark \
  RUTA_REFERENCIA.lyricsfile.yaml outputs/JOB_ID/lyrics.lyricsfile.yaml \
  --output reports/comparison.json
```

Para una corrida sin referencia externa, prepara el audio con `--no-lrclib` y entrega la
referencia solo al comparador. Usa la misma edición y el mismo inicio del audio.

El reporte separa voz principal y todas las voces, cuenta ediciones de tokens y mide desvíos
de inicio y fin en coincidencias textuales. Incluye cobertura y los mayores desvíos.
No corrige automáticamente un desfase global. Sílabas, contracciones, estribillos repetidos y
voces simultáneas pueden distorsionar la comparación: `token_error_rate` no equivale directamente
a WER lingüístico ni a precisión acústica. Las etiquetas de voz no se califican como identidades.
