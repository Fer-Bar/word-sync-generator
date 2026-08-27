import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import type { ChangeEvent, Dispatch } from 'react'
import { AudioTransport } from './components/AudioTransport'
import { LyricsEditor } from './components/LyricsEditor'
import { parseTranscript } from './domain/transcript'
import { formatTimestamp } from './domain/time'
import type { EditDocument, Transcript } from './domain/types'
import { editorReducer, initialState } from './state/editorReducer'
import type { EditorAction } from './state/editorReducer'

interface JobResponse {
  edit: EditDocument
  media: { url: string; name: string; type: 'audio' }
}

function queryConnection() {
  const params = new URLSearchParams(window.location.search)
  return { api: params.get('api'), token: params.get('token') }
}

export function App() {
  const [state, dispatch] = useReducer(editorReducer, initialState)
  const [document, setDocument] = useState<EditDocument | null>(null)
  const [saveStatus, setSaveStatus] = useState('No unsaved changes')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [loopWord, setLoopWord] = useState(false)
  const [active, setActive] = useState<{ segmentId: string | null; wordId: string | null }>({
    segmentId: null,
    wordId: null,
  })
  const audioRef = useRef<HTMLAudioElement>(null)
  const connection = useMemo(queryConnection, [])

  const loadTranscript = useCallback((transcript: Transcript) => {
    dispatch({ type: 'LOAD_TRANSCRIPT', payload: transcript })
    setSaveStatus('No unsaved changes')
  }, [])

  useEffect(() => {
    if (!connection.api || !connection.token) return
    const controller = new AbortController()
    fetch(`${connection.api}/api/job`, {
      headers: { 'X-Karaoke-Token': connection.token },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error((await response.json()).detail || 'Unable to load job')
        return response.json() as Promise<JobResponse>
      })
      .then((job) => {
        setDocument(job.edit)
        loadTranscript(parseTranscript(JSON.stringify(job.edit.transcript)))
        dispatch({ type: 'LOAD_MEDIA', payload: job.media })
      })
      .catch((error: Error) => {
        if (error.name !== 'AbortError') setLoadError(error.message)
      })
    return () => controller.abort()
  }, [connection, loadTranscript])

  const dispatchEdit: Dispatch<EditorAction> = useCallback((action) => {
    dispatch(action)
    setSaveStatus('Unsaved changes')
  }, [])

  const save = useCallback(async () => {
    if (!connection.api || !connection.token || !document || !state.transcript) return
    setSaveStatus('Saving…')
    try {
      const response = await fetch(`${connection.api}/api/job`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'X-Karaoke-Token': connection.token,
        },
        body: JSON.stringify({ ...document, transcript: state.transcript }),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail || 'Unable to save job')
      setDocument(body.edit)
      setSaveStatus(`Saved revision ${body.edit.revision}`)
    } catch (error) {
      setSaveStatus(error instanceof Error ? error.message : 'Unable to save job')
    }
  }, [connection, document, state.transcript])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void save()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [save])

  const selectedWord =
    state.selectedSegmentIndex === null || state.selectedWordIndex === null
      ? null
      : state.transcript?.segments[state.selectedSegmentIndex]?.words[state.selectedWordIndex] ?? null

  const seek = useCallback((time: number) => {
    if (audioRef.current) audioRef.current.currentTime = Math.max(0, time)
  }, [])

  const getPlayhead = useCallback(() => audioRef.current?.currentTime ?? 0, [])

  const replaySelected = useCallback(() => {
    if (!audioRef.current || !selectedWord) return
    audioRef.current.currentTime = selectedWord.start
    void audioRef.current.play()
  }, [selectedWord])

  const handleAudioTime = useCallback((time: number) => {
    const audio = audioRef.current
    const transcript = state.transcript
    if (!audio || !transcript) return
    const segment = transcript.segments.find((item) => time >= item.start && time <= item.end)
    const word = segment?.words.find((item) => time >= item.start && time <= item.end)
    setActive((current) =>
      current.segmentId === (segment?.id ?? null) && current.wordId === (word?.id ?? null)
        ? current
        : { segmentId: segment?.id ?? null, wordId: word?.id ?? null },
    )
  }, [state.transcript])

  const handleTranscriptFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    file.text()
      .then((text) => {
        setDocument(null)
        loadTranscript(parseTranscript(text))
      })
      .catch((error: Error) => setLoadError(error.message))
  }

  const handleAudioFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    dispatch({ type: 'LOAD_MEDIA', payload: { url: URL.createObjectURL(file), name: file.name, type: 'audio' } })
  }

  const durationHint =
    state.transcript?.song.duration ??
    (state.transcript?.segments.length ? state.transcript.segments[state.transcript.segments.length - 1].end + 5 : 60)

  return (
    <div className="min-h-screen bg-[#0b0f19] text-gray-100">
      <header className="sticky top-0 z-20 border-b border-gray-800 bg-gray-950/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="m-0 text-lg font-bold">Karaoke transcript editor</h1>
            <p className="m-0 text-xs text-gray-400">{state.transcript?.song.title ?? 'Open a prepared job to begin'}</p>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400">{saveStatus}</span>
            <button className="primary-button" disabled={!document || !state.transcript || saveStatus === 'Saving…'} onClick={() => void save()}>
              Save
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl space-y-4 p-4">
        {loadError ? <p className="warning error">{loadError}</p> : null}
        <AudioTransport
          audioRef={audioRef}
          src={state.mediaUrl}
          durationHint={durationHint}
          loopRange={loopWord && selectedWord ? { start: selectedWord.start, end: selectedWord.end } : null}
          onTimeChange={handleAudioTime}
        />
        <section className="flex flex-wrap items-center gap-3 rounded-xl border border-gray-800 bg-gray-900 p-4 text-xs text-gray-400">
          <span>All times use MM:SS.mmm</span>
          <span className="font-mono text-gray-500">Current word: {active.wordId ?? 'none'}</span>
          <span className="font-mono text-gray-500">Duration: {formatTimestamp(durationHint)}</span>
          <div className="flex flex-wrap items-center gap-3">
            <label className="editor-button cursor-pointer">
              Load audio
              <input className="hidden" type="file" accept="audio/*" onChange={handleAudioFile} />
            </label>
            <label className="editor-button cursor-pointer">
              Load transcript
              <input className="hidden" type="file" accept="application/json,.json" onChange={handleTranscriptFile} />
            </label>
            <label className="flex items-center gap-2 text-xs text-gray-300">
              <input type="checkbox" checked={loopWord} onChange={(event) => setLoopWord(event.target.checked)} />
              Loop selected word
            </label>
          </div>
        </section>

        <LyricsEditor
          state={state}
          dispatch={dispatch}
          dispatchEdit={dispatchEdit}
          activeSegmentId={active.segmentId}
          activeWordId={active.wordId}
          getPlayhead={getPlayhead}
          seek={seek}
          replaySelected={replaySelected}
        />
      </main>
    </div>
  )
}

export default App
