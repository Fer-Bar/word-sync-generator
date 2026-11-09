# Pruebas que comprueban resultados

[Volver al README](../README.md)

## Ejecutar

La suite completa requiere `ffmpeg` y `ffprobe` disponibles en `PATH`, además de
Chromium. En Ubuntu/Debian, FFmpeg/FFprobe se instalan con `sudo apt-get install ffmpeg`.
El workflow `Checks` instala estos requisitos.

```bash
uv sync --locked --dev --python 3.12
uv run playwright install --with-deps chromium
uv run ruff check .
uv run pytest -q
uv build
```

Para iterar sobre la preparación local y el render:

```bash
uv run pytest -q tests/test_render_workflow.py tests/test_render_lifecycle.py
```

Los renders de `test_render_workflow.py` y `test_poster_graphics.py` usan el FFmpeg
incluido en `imageio-ffmpeg`; el flujo de notebook de `test_notebook_pipeline.py` usa
FFmpeg/FFprobe del sistema. El caso de navegador falla en CI si falta Chromium;
localmente se omite con una explicación. Una ejecución con omisiones no equivale a
haber probado los escenarios omitidos.

## Qué se comprueba

- **Render desde un proyecto:** WAV válidos y distintos para original, instrumental y
  voces; LyricsFile YAML con tiempos por palabra; validación, ASS/SRT, gráficos, ZIP,
  extracción, FFmpeg y empaquetado reales. Se vuelve a extraer el resultado,
  se decodifica todo el video, se verifican duración/resolución/fps, píxeles de las letras,
  contenido de subtítulos y frecuencia del audio. Intercambiar las pistas de karaoke
  y lyrics debe fallar aunque ambos MP4 existan.
- **Video sin subtítulos:** codificación y decodificación reales para comprobar el
  fondo limpio y el audio, en vez de comprobar que un comando no contiene `-vf`.
- **Preparación y recuperación del cliente:** el proyecto y el bundle son reales.
  Solo el transporte a Colab se controla para reproducir cancelaciones, reintentos,
  cierre fallido y error remoto sin consumir una sesión GPU. También se verifica que
  audio ausente o letras inválidas no creen una sesión ni modifiquen el proyecto, y
  que `--dry-run` no escriba archivos.
- **Procesos auxiliares:** un proceso Python real produce stdout/stderr y códigos de
  salida para comprobar la propagación del error del instalador, sin instalar nada.
- **Navegador:** `test_render_workflow.py` también ejecuta el bundle con Braccato,
  Chromium y FFmpeg reales. Usa Montserrat (incluida en el repositorio) y su licencia
  OFL como entrada tipográfica de prueba, conservando los nombres canónicos del bundle
  solo dentro del directorio temporal. No necesita descargar Switzer. La instalación
  del navegador se omite durante el render porque es un requisito previo. Las pruebas
  existentes específicas de Switzer en `test_browser_lyrics.py` requieren la fuente
  en caché y pueden omitirse cuando no está disponible.

Los renders ASS de `test_render_workflow.py` y `test_poster_graphics.py` desactivan
únicamente la instalación/descarga de fuentes del runtime: no deben ejecutar `apt` ni
cambiar fuentes del sistema durante una prueba.
Usan las fuentes ya disponibles. No sustituyen el detector de NVENC, FFmpeg, la creación
de archivos ni el empaquetado. Como la dependencia local no incluye FFprobe, el adaptador
de duración del test decodifica el audio real a PCM con FFmpeg y cuenta sus muestras.
No usa una duración fijada por el fixture. El comando FFprobe de producción no queda
validado por estas pruebas; sí la selección de audio, composición y salida decodificada.

## Pruebas retiradas y su sustituto

En `test_karaoke_job.py` se retiraron seis casos cuyo resultado era principalmente
inspeccionar llamadas de mocks:

| Casos anteriores | Cobertura funcional |
| --- | --- |
| Comando FFmpeg con/sin ASS y encaminamiento de subtítulos | `test_render_workflow.py`: video decodificado, letras visibles y ASS/SRT de cada modo |
| Render con módulo de navegador completamente simulado | Bundle/Chromium/FFmpeg real con fuente incluida en `test_render_workflow.py` |
| Éxito/error del instalador con `subprocess.run` simulado | Proceso Python real con ambos códigos de salida |

El fixture de `test_render_lifecycle.py` ya no sustituye lectura del proyecto, resolución
de archivos, carga de YAML, conversión de letras, generación de ASS/SRT ni creación de ZIP.
Las pruebas conservan el control de la frontera Colab para provocar fallos reproducibles.

## Criterio para cambios futuros

1. Empezar por una entrada real pequeña y un resultado observable: archivo legible,
   audio correcto, letra visible, error útil o recuperación sin pérdida de datos.
2. Sustituir solo servicios externos o fallos difíciles de provocar de forma segura.
   No simular cada función del camino que se quiere probar.
3. Mantener unitarias para reglas puras, casos límite y adaptadores a modelos/red cuando
   no haya una alternativa funcional razonable. No borrar su cobertura solo por usar mocks.
4. Retirar una prueba solo después de identificar qué regresión detectaba y qué prueba
   conserva esa protección. No perseguir porcentajes de cobertura ni cantidades de tests.

La suite local no valida autenticación/transferencias reales de Colab, precisión acústica
CTC/ASR, disponibilidad de proveedores ni velocidad de GPU. Esos escenarios requieren
pruebas separadas con cuentas, audio autorizado y referencias revisadas. Los dobles de
modelos siguen siendo pruebas de contrato/control de flujo, no evidencia de calidad del
modelo.

## Evitar pruebas ligadas a una entrega puntual

Usa títulos, artistas e identificadores sintéticos como datos de prueba.
Una regresión debe explicar el comportamiento que protege, no conservar la apariencia
exacta de una canción que se generó una vez.

`test_poster_graphics.py` prueba los estilos reutilizables que la CLI llama `fomo` y
`fomo-xerox`; esos nombres son opciones de la aplicación, no canciones de referencia.
Conserva los límites de texto, alineación, transparencia, repetibilidad y contraste de
paletas. No fija una media o desviación de ruido para imitar una portada determinada.
Las combinaciones de límites de título/layout/alineación siguen cubiertas.

El flujo de gráficos usa audio y subtítulos válidos y decodifica ambos MP4. Comprueba
que el intro llegue a sus fotogramas, desaparezca antes de la primera letra y que
las letras aparezcan después. Comprueba también que los modos del estilo predeterminado
se distingan y que el texto tenga contraste con el fondo según la paleta elegida, sin
usar otro gráfico del mismo generador como única referencia. Sustituye las pruebas que
solo inspeccionaban llamadas al renderizador.
Las tolerancias de píxeles cubren pérdidas de compresión de video, no una estética por
canción. La selección del fotograma de miniatura también usa un video real de dos colores.

Los datos ficticios siguen siendo apropiados para pruebas de copiar/mover archivos o
verificar hashes cuando su contrato no incluye decodificarlos. Los comparadores de
alineación conservan ejemplos sintéticos y verificaciones de integridad; no se borran
por haber nacido de un incidente concreto ni se presentan como pruebas de inferencia.
