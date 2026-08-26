import { useRef } from 'react'
import type { ChangeEvent, Dispatch, FC } from 'react'
import { FileAudio, FileJson, FileVideo, Music, Sparkles, Upload } from 'lucide-react'
import { parseTranscript } from '../domain/transcript'
import type { EditorAction, EditorState } from '../state/editorReducer'

interface Props {
  state: EditorState
  dispatch: Dispatch<EditorAction>
}

const SAMPLE_TRANSCRIPT = {
  schema_version: 1,
  song: {
    title: 'Sample Track - Karaoke Edition',
    uploader: 'Colab Video Generator',
    duration: 30.0,
  },
  transcription: {
    engine: 'faster-whisper',
    model: 'large-v3',
    language: 'en',
  },
  segments: [
    {
      id: 's0',
      start: 1.2,
      end: 4.5,
      text: 'Welcome to the karaoke web editor',
      words: [
        { id: 's0-w0', start: 1.2, end: 1.8, text: 'Welcome' },
        { id: 's0-w1', start: 1.9, end: 2.1, text: 'to' },
        { id: 's0-w2', start: 2.2, end: 2.4, text: 'the' },
        { id: 's0-w3', start: 2.5, end: 3.1, text: 'karaoke' },
        { id: 's0-w4', start: 3.2, end: 3.7, text: 'web' },
        { id: 's0-w5', start: 3.8, end: 4.5, text: 'editor' },
      ],
    },
    {
      id: 's1',
      start: 5.5,
      end: 9.0,
      text: 'Align your lyrics with precision',
      words: [
        { id: 's1-w0', start: 5.5, end: 6.0, text: 'Align' },
        { id: 's1-w1', start: 6.1, end: 6.4, text: 'your' },
        { id: 's1-w2', start: 6.5, end: 7.2, text: 'lyrics' },
        { id: 's1-w3', start: 7.3, end: 7.6, text: 'with' },
        { id: 's1-w4', start: 7.7, end: 9.0, text: 'precision' },
      ],
    },
    {
      id: 's2',
      start: 10.5,
      end: 14.2,
      text: 'Customize fonts colors and backgrounds easily',
      words: [
        { id: 's2-w0', start: 10.5, end: 11.2, text: 'Customize' },
        { id: 's2-w1', start: 11.3, end: 11.8, text: 'fonts' },
        { id: 's2-w2', start: 11.9, end: 12.5, text: 'colors' },
        { id: 's2-w3', start: 12.6, end: 12.8, text: 'and' },
        { id: 's2-w4', start: 12.9, end: 13.7, text: 'backgrounds' },
        { id: 's2-w5', start: 13.8, end: 14.2, text: 'easily' },
      ],
    },
  ],
}

export const FileLoader: FC<Props> = ({ state, dispatch }) => {
  const jsonInputRef = useRef<HTMLInputElement>(null)
  const mediaInputRef = useRef<HTMLInputElement>(null)

  const handleJsonUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const text = e.target?.result as string
        const parsed = parseTranscript(text)
        dispatch({ type: 'LOAD_TRANSCRIPT', payload: parsed })
      } catch (err: any) {
        alert(`Error al cargar el transcript JSON: ${err.message}`)
      }
    }
    reader.readAsText(file)
  }

  const handleMediaUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    if (state.mediaUrl) {
      URL.revokeObjectURL(state.mediaUrl)
    }

    const objectUrl = URL.createObjectURL(file)
    const isVideo = file.type.startsWith('video/') || file.name.endsWith('.mp4') || file.name.endsWith('.webm')
    dispatch({
      type: 'LOAD_MEDIA',
      payload: {
        url: objectUrl,
        name: file.name,
        type: isVideo ? 'video' : 'audio',
      },
    })
  }

  const loadSample = () => {
    const parsed = parseTranscript(JSON.stringify(SAMPLE_TRANSCRIPT))
    dispatch({ type: 'LOAD_TRANSCRIPT', payload: parsed })
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 shadow-xl">
      <div className="flex flex-col md:flex-row items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Music className="w-5 h-5 text-cyan-400" />
            {state.transcript ? state.transcript.song.title : 'Editor de Karaoke y Subtítulos ASS'}
          </h2>
          <p className="text-sm text-gray-400 mt-1">
            {state.transcript
              ? `${state.transcript.segments.length} segmentos • ${state.transcript.segments.reduce((acc, s) => acc + s.words.length, 0)} palabras sincronizadas`
              : 'Carga un archivo *_transcript.json y un video/audio de referencia para comenzar.'}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <input
            type="file"
            ref={jsonInputRef}
            accept=".json,application/json"
            onChange={handleJsonUpload}
            className="hidden"
          />
          <button
            onClick={() => jsonInputRef.current?.click()}
            className="flex items-center gap-2 px-4 py-2 bg-cyan-600 hover:bg-cyan-500 text-white text-sm font-medium rounded-lg transition-colors shadow-sm"
          >
            <FileJson className="w-4 h-4" />
            {state.transcript ? 'Cambiar Transcript JSON' : 'Cargar Transcript (*.json)'}
          </button>

          <input
            type="file"
            ref={mediaInputRef}
            accept="video/*,audio/*,.mp4,.mp3,.flac,.wav,.m4a"
            onChange={handleMediaUpload}
            className="hidden"
          />
          <button
            onClick={() => mediaInputRef.current?.click()}
            className="flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm font-medium rounded-lg border border-gray-700 transition-colors"
          >
            {state.mediaType === 'video' ? (
              <FileVideo className="w-4 h-4 text-purple-400" />
            ) : state.mediaType === 'audio' ? (
              <FileAudio className="w-4 h-4 text-emerald-400" />
            ) : (
              <Upload className="w-4 h-4 text-gray-400" />
            )}
            {state.mediaName ? `Media: ${state.mediaName.slice(0, 20)}...` : 'Cargar Audio/Video'}
          </button>

          {!state.transcript && (
            <button
              onClick={loadSample}
              className="flex items-center gap-2 px-4 py-2 bg-purple-900/60 hover:bg-purple-800/80 text-purple-200 text-sm font-medium rounded-lg border border-purple-700/50 transition-colors"
            >
              <Sparkles className="w-4 h-4 text-purple-300" />
              Cargar Ejemplo
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
