# Componentes de terceros

Apache-2.0 se aplica al código propio de Lyrics Generator. No cambia las licencias de
bibliotecas, pesos de modelos, tipografías ni contenido aportado por el usuario.

## Recursos incluidos

- **Braccato Core 1.6.2**, de Boidushya Bhattacharya: MIT. Se conservan su
  [licencia](src/karaoke_app/assets/braccato/LICENSE) y
  [procedencia y checksum](src/karaoke_app/assets/braccato/PROVENANCE.json).
  Código original: [better-lyrics/braccato](https://github.com/better-lyrics/braccato).
- **Anton, Montserrat y Barlow Condensed**: SIL Open Font License 1.1.
  Los avisos de autoría y condiciones acompañan a cada familia en
  [assets/fonts](src/karaoke_app/assets/fonts/).

## Recursos descargados y dependencias

- **Switzer**, de Indian Type Foundry, se descarga desde [Fontshare](https://www.fontshare.com/)
  con su licencia; la aplicación conserva el archivo de licencia junto a la fuente en caché.
- El modelo [mms-300m-1130-forced-aligner](https://huggingface.co/MahmoudAshraf/mms-300m-1130-forced-aligner)
  declara **CC-BY-NC-4.0**. La licencia del código propio no autoriza el uso comercial de esos pesos.
- [CTC Forced Aligner](https://github.com/MahmoudAshraf97/ctc-forced-aligner), Demucs,
  faster-whisper y sus modelos se instalan en Colab; conserva y revisa las condiciones
  de las versiones utilizadas antes de redistribuirlos.
- FFmpeg y Chromium son componentes externos. Sus condiciones dependen de la distribución
  y las opciones de compilación; no están relicenciados bajo Apache-2.0 por este proyecto.

Las versiones locales están registradas en [uv.lock](uv.lock), y las remotas en
[colab/requirements.txt](colab/requirements.txt). El [README](README.md#tecnologías-y-proyectos)
identifica los proyectos y servicios utilizados, incluido el editor externo LyricsEditor.
Los audios, letras, portadas y logos no quedan cubiertos por la licencia del código.
