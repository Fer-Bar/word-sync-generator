import { memo, useEffect, useState } from 'react'
import type { Dispatch, FC } from 'react'
import { formatTimestamp, parseTimestamp } from '../domain/time'
import type { EditorAction, EditorState } from '../state/editorReducer'

interface Props {
  state: EditorState
  dispatch: Dispatch<EditorAction>
  dispatchEdit: Dispatch<EditorAction>
  activeSegmentId: string | null
  activeWordId: string | null
  getPlayhead: () => number
  seek: (time: number) => void
  replaySelected: () => void
}

const LyricsEditorComponent: FC<Props> = ({
  state,
  dispatch,
  dispatchEdit,
  activeSegmentId,
  activeWordId,
  getPlayhead,
  seek,
  replaySelected,
}) => {
  const [wordText, setWordText] = useState('')
  const [pattern, setPattern] = useState('')
  const [boundaryIndex, setBoundaryIndex] = useState(0)
  const [startText, setStartText] = useState('')
  const [endText, setEndText] = useState('')
  const [timeError, setTimeError] = useState<string | null>(null)
  const transcript = state.transcript
  const segmentIndex = state.selectedSegmentIndex
  const wordIndex = state.selectedWordIndex
  const selectedSegment = segmentIndex === null ? null : transcript?.segments[segmentIndex] ?? null
  const selectedWord = wordIndex === null ? null : selectedSegment?.words[wordIndex] ?? null
  const selectedPattern = selectedWord?.timing?.map((fragment) => fragment.text).join('|') ?? ''

  useEffect(() => {
    setWordText(selectedWord?.text ?? '')
    setPattern(selectedPattern)
    setStartText(selectedWord ? formatTimestamp(selectedWord.start) : '')
    setEndText(selectedWord ? formatTimestamp(selectedWord.end) : '')
    setTimeError(null)
    setBoundaryIndex(0)
  }, [selectedPattern, selectedWord?.end, selectedWord?.id, selectedWord?.start, selectedWord?.text])

  if (!transcript) {
    return <p className="rounded-xl border border-gray-800 bg-gray-900 p-6 text-gray-400">Load a prepared job or local transcript.</p>
  }

  const editSelected = (action: EditorAction) => dispatchEdit(action)
  const selection = segmentIndex !== null && wordIndex !== null ? { segmentIndex, wordIndex } : null
  const patternValid = !selectedWord || !pattern || (pattern.includes('|') && pattern.split('|').every(Boolean) && pattern.split('|').join('') === selectedWord.text)
  const applyTimestamps = () => {
    if (!selection) return
    const start = parseTimestamp(startText)
    const end = parseTimestamp(endText)
    if (start === null || end === null) {
      setTimeError('Use MM:SS.mmm, for example 01:23.450.')
      return
    }
    if (end <= start) {
      setTimeError('End must be later than start.')
      return
    }
    setTimeError(null)
    editSelected({ type: 'UPDATE_WORD', payload: { ...selection, updates: { start, end } } })
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <section className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gray-800 bg-gray-900 p-3">
          <button className="editor-button" disabled={!state.history.length} onClick={() => dispatchEdit({ type: 'UNDO' })}>Undo</button>
          <button className="editor-button" disabled={!state.future.length} onClick={() => dispatchEdit({ type: 'REDO' })}>Redo</button>
          {state.validationErrors.slice(0, 4).map((error, index) => (
            <span key={`${error.field}-${index}`} className={error.type === 'error' ? 'warning error' : 'warning'}>
              {error.message}
            </span>
          ))}
        </div>

        <div className="max-h-[65vh] space-y-2 overflow-y-auto pr-1">
          {transcript.segments.map((segment, currentSegmentIndex) => (
            <article
              key={segment.id}
              className={`rounded-xl border p-3 ${segment.id === activeSegmentId ? 'border-cyan-500 bg-cyan-950/20' : 'border-gray-800 bg-gray-900'}`}
            >
              <div className="mb-2 flex items-center justify-between gap-2 text-xs text-gray-400">
                <button
                  className="font-mono text-cyan-300"
                  onClick={() => {
                    dispatch({ type: 'SELECT_SEGMENT', payload: currentSegmentIndex })
                    seek(segment.start)
                  }}
                >
                   Line {currentSegmentIndex + 1} · {formatTimestamp(segment.start)}–{formatTimestamp(segment.end)}
                </button>
                <button
                  className="editor-button"
                  disabled={currentSegmentIndex === transcript.segments.length - 1}
                  onClick={() => editSelected({ type: 'MERGE_LINE_NEXT', payload: { segmentIndex: currentSegmentIndex } })}
                >
                  Merge next
                </button>
              </div>
              <div className="flex flex-wrap gap-2">
                {segment.words.map((word, currentWordIndex) => {
                  const isSelected = currentSegmentIndex === segmentIndex && currentWordIndex === wordIndex
                  return (
                    <button
                      key={word.id}
                      className={`word-chip ${word.id === activeWordId ? 'active' : ''} ${isSelected ? 'selected' : ''}`}
                      onClick={() => {
                        dispatch({
                          type: 'SELECT_WORD',
                          payload: { segmentIndex: currentSegmentIndex, wordIndex: currentWordIndex },
                        })
                        seek(word.start)
                      }}
                    >
                      <strong>{word.text}</strong>
                       <span>{formatTimestamp(word.start)}–{formatTimestamp(word.end)}</span>
                    </button>
                  )
                })}
              </div>
            </article>
          ))}
        </div>
      </section>

      <aside className="h-fit space-y-4 rounded-xl border border-gray-800 bg-gray-900 p-4 lg:sticky lg:top-24">
        <div>
          <h2 className="m-0 text-base font-semibold text-white">Selected word</h2>
          <p className="mt-1 text-xs text-gray-400">Correct text, line placement, and exact timing.</p>
        </div>
        {selectedWord && selection && selectedSegment ? (
          <>
            <label className="field-label">
              Text
              <div className="flex gap-2">
                <input className="editor-input min-w-0 flex-1" value={wordText} onChange={(event) => setWordText(event.target.value)} />
                <button
                  className="primary-button"
                  disabled={!wordText.trim() || wordText.trim() === selectedWord.text}
                  onClick={() => editSelected({ type: 'UPDATE_WORD', payload: { ...selection, updates: { text: wordText } } })}
                >
                  Apply
                </button>
              </div>
            </label>

            <div className="grid grid-cols-2 gap-2">
              <label className="field-label">
                Start
                <input
                  className="editor-input font-mono"
                  value={startText}
                  onChange={(event) => setStartText(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') applyTimestamps()
                  }}
                  inputMode="decimal"
                />
              </label>
              <label className="field-label">
                End
                <input
                  className="editor-input font-mono"
                  value={endText}
                  onChange={(event) => setEndText(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') applyTimestamps()
                  }}
                  inputMode="decimal"
                />
              </label>
              <button className="primary-button col-span-2" onClick={applyTimestamps}>Apply timestamps</button>
              {timeError ? <p className="warning error col-span-2 m-0">{timeError}</p> : null}
               <button className="editor-button" onClick={() => editSelected({ type: 'UPDATE_WORD', payload: { ...selection, updates: { start: getPlayhead() } } })}>Start = playhead</button>
               <button className="editor-button" onClick={() => editSelected({ type: 'UPDATE_WORD', payload: { ...selection, updates: { end: getPlayhead() } } })}>End = playhead</button>
             </div>

            {(['start', 'end'] as const).map((boundary) => (
              <div key={boundary} className="flex flex-wrap items-center gap-1">
                <span className="w-10 text-xs capitalize text-gray-400">{boundary}</span>
                 {[-0.05, -0.01, -0.001, 0.001, 0.01, 0.05].map((delta) => (
                  <button
                    key={delta}
                    className="editor-button"
                    onClick={() => editSelected({ type: 'NUDGE_BOUNDARY', payload: { ...selection, boundary, delta } })}
                  >
                     {delta > 0 ? '+' : ''}{Math.round(delta * 1000)} ms
                  </button>
                ))}
              </div>
            ))}

            <div className="grid grid-cols-2 gap-2">
              <button className="editor-button" disabled={wordIndex === 0} onClick={() => editSelected({ type: 'SPLIT_LINE', payload: selection })}>Split line before</button>
              <button className="editor-button" onClick={() => editSelected({ type: 'MOVE_WORD_NEXT', payload: selection })}>Move to next line</button>
              <button className="editor-button" onClick={() => editSelected({ type: 'NORMALIZE_LINE', payload: { segmentIndex } })}>Normalize line gaps</button>
              <button className="editor-button" onClick={replaySelected}>Replay word</button>
              <button
                className="editor-button col-span-2 text-red-300"
                disabled={transcript.segments.length === 1 && selectedSegment.words.length === 1}
                onClick={() => editSelected({ type: 'DELETE_WORD', payload: selection })}
              >
                Remove word
              </button>
            </div>

            <div className="space-y-2 border-t border-gray-800 pt-4">
              <label className="field-label">
                Sustained-vowel pattern
                <input className="editor-input" value={pattern} placeholder="am|o|r" onChange={(event) => setPattern(event.target.value)} />
              </label>
              {!patternValid ? <p className="m-0 text-xs text-amber-300">Fragments must be non-empty and join exactly to “{selectedWord.text}”.</p> : null}
              <button
                className="editor-button w-full"
                disabled={!patternValid || !pattern.includes('|')}
                onClick={() => editSelected({ type: 'SET_TIMING_PATTERN', payload: { ...selection, pattern } })}
              >
                Apply fragment pattern
              </button>
              {selectedWord.timing && selectedWord.timing.length > 1 ? (
                <div className="space-y-2">
                  <label className="field-label">
                    Internal boundary
                    <select className="editor-input" value={boundaryIndex} onChange={(event) => setBoundaryIndex(Number(event.target.value))}>
                      {selectedWord.timing.slice(0, -1).map((fragment, index) => (
                         <option key={fragment.id} value={index}>
                           {fragment.text} | {selectedWord.timing![index + 1].text} ({formatTimestamp(fragment.end)})
                         </option>
                      ))}
                    </select>
                  </label>
                  <div className="flex flex-wrap gap-1">
                     {[-0.05, -0.01, -0.001, 0.001, 0.01, 0.05].map((delta) => (
                      <button
                        key={delta}
                        className="editor-button"
                        onClick={() => editSelected({
                          type: 'SET_FRAGMENT_BOUNDARY',
                          payload: { ...selection, boundaryIndex, value: selectedWord.timing![boundaryIndex].end + delta },
                        })}
                      >
                         {delta > 0 ? '+' : ''}{Math.round(delta * 1000)} ms
                      </button>
                    ))}
                    <button
                      className="editor-button"
                      onClick={() => editSelected({ type: 'SET_FRAGMENT_BOUNDARY', payload: { ...selection, boundaryIndex, value: getPlayhead() } })}
                    >
                      Set from playhead
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          </>
        ) : (
          <p className="text-sm text-gray-400">Select a word in the transcript.</p>
        )}
      </aside>
    </div>
  )
}

export const LyricsEditor = memo(LyricsEditorComponent)
