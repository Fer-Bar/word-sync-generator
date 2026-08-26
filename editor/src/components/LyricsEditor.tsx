import { useState } from 'react'
import type { Dispatch, FC } from 'react'
import {
  Clock,
  Edit2,
  MoveLeft,
  MoveRight,
  Plus,
  Redo2,
  Search,
  Trash2,
  Undo2,
} from 'lucide-react'
import type { EditorAction, EditorState } from '../state/editorReducer'

interface Props {
  state: EditorState
  dispatch: Dispatch<EditorAction>
}

export const LyricsEditor: FC<Props> = ({ state, dispatch }) => {
  const [searchQuery, setSearchQuery] = useState('')
  const [editingWordId, setEditingWordId] = useState<string | null>(null)
  const [editingText, setEditingText] = useState('')

  if (!state.transcript) {
    return (
      <div className="p-8 text-center text-gray-400 bg-gray-900 border border-gray-800 rounded-xl">
        <p>No hay transcript cargado. Carga un archivo JSON arriba o haz clic en "Cargar Ejemplo".</p>
      </div>
    )
  }

  const { segments } = state.transcript
  const filteredSegments = segments
    .map((seg, segIdx) => ({ seg, segIdx }))
    .filter(({ seg }) =>
      !searchQuery || seg.text.toLowerCase().includes(searchQuery.toLowerCase())
    )

  const handleStartEditText = (wordId: string, currentText: string) => {
    setEditingWordId(wordId)
    setEditingText(currentText)
  }

  const handleSaveEditText = (segIdx: number, wordIdx: number) => {
    if (editingText.trim()) {
      dispatch({
        type: 'UPDATE_WORD',
        payload: {
          segmentIndex: segIdx,
          wordIndex: wordIdx,
          updates: { text: editingText.trim() },
        },
      })
    }
    setEditingWordId(null)
  }

  const handleAddWordPrompt = (segIdx: number, afterWordIdx: number) => {
    const text = prompt('Escribe el texto de la nueva palabra:')
    if (text && text.trim()) {
      dispatch({
        type: 'ADD_WORD',
        payload: {
          segmentIndex: segIdx,
          afterWordIndex: afterWordIdx,
          text: text.trim(),
        },
      })
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Top Toolbar: Search, Undo, Redo */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-gray-900 border border-gray-800 p-3 rounded-xl">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search className="w-4 h-4 absolute left-3 top-2.5 text-gray-400" />
          <input
            type="text"
            placeholder="Buscar en la letra..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 text-sm text-gray-200 pl-9 pr-4 py-1.5 rounded-lg focus:outline-none focus:border-cyan-500 transition-colors"
          />
        </div>

        {/* Undo / Redo */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => dispatch({ type: 'UNDO' })}
            disabled={state.history.length === 0}
            title="Deshacer cambio (Ctrl+Z)"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:hover:bg-gray-800 text-gray-200 text-xs font-medium rounded-lg border border-gray-700 transition-colors"
          >
            <Undo2 className="w-3.5 h-3.5" />
            Deshacer ({state.history.length})
          </button>
          <button
            onClick={() => dispatch({ type: 'REDO' })}
            disabled={state.future.length === 0}
            title="Rehacer cambio (Ctrl+Y)"
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 disabled:opacity-40 disabled:hover:bg-gray-800 text-gray-200 text-xs font-medium rounded-lg border border-gray-700 transition-colors"
          >
            <Redo2 className="w-3.5 h-3.5" />
            Rehacer ({state.future.length})
          </button>
        </div>
      </div>

      {/* Segments List */}
      <div className="flex flex-col gap-3 max-h-[600px] overflow-y-auto pr-1">
        {filteredSegments.map(({ seg, segIdx }) => {
          const isSegmentActive =
            state.currentTime >= seg.start && state.currentTime <= seg.end
          const isSegmentSelected = state.selectedSegmentIndex === segIdx

          return (
            <div
              key={seg.id || `seg-${segIdx}`}
              onClick={() => dispatch({ type: 'SELECT_SEGMENT', payload: segIdx })}
              className={`border rounded-xl p-4 transition-all ${
                isSegmentActive
                  ? 'bg-cyan-950/20 border-cyan-500/60 shadow-lg ring-1 ring-cyan-500/30'
                  : isSegmentSelected
                  ? 'bg-gray-850 border-gray-700 shadow-md'
                  : 'bg-gray-900 border-gray-800 hover:border-gray-700'
              }`}
            >
              {/* Segment Header */}
              <div className="flex flex-wrap items-center justify-between gap-2 pb-3 mb-3 border-b border-gray-800">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 bg-gray-800 text-cyan-300 font-mono text-xs font-bold rounded">
                    #{segIdx + 1}
                  </span>
                  <span className="flex items-center gap-1 text-xs font-mono text-gray-400">
                    <Clock className="w-3 h-3" />
                    {seg.start.toFixed(2)}s - {seg.end.toFixed(2)}s (
                    {(seg.end - seg.start).toFixed(2)}s)
                  </span>
                </div>

                {/* Segment Shift Controls */}
                <div className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                  <span className="text-[11px] text-gray-400 mr-1">Mover segmento:</span>
                  <button
                    onClick={() =>
                      dispatch({
                        type: 'SHIFT_SEGMENT',
                        payload: { segmentIndex: segIdx, delta: -0.1 },
                      })
                    }
                    title="Atrasar segmento 100ms"
                    className="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded border border-gray-700 transition-colors"
                  >
                    -100ms
                  </button>
                  <button
                    onClick={() =>
                      dispatch({
                        type: 'SHIFT_SEGMENT',
                        payload: { segmentIndex: segIdx, delta: -0.05 },
                      })
                    }
                    title="Atrasar segmento 50ms"
                    className="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded border border-gray-700 transition-colors"
                  >
                    -50ms
                  </button>
                  <button
                    onClick={() =>
                      dispatch({
                        type: 'SHIFT_SEGMENT',
                        payload: { segmentIndex: segIdx, delta: 0.05 },
                      })
                    }
                    title="Adelantar segmento 50ms"
                    className="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded border border-gray-700 transition-colors"
                  >
                    +50ms
                  </button>
                  <button
                    onClick={() =>
                      dispatch({
                        type: 'SHIFT_SEGMENT',
                        payload: { segmentIndex: segIdx, delta: 0.1 },
                      })
                    }
                    title="Adelantar segmento 100ms"
                    className="px-2 py-1 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded border border-gray-700 transition-colors"
                  >
                    +100ms
                  </button>
                </div>
              </div>

              {/* Words Chips in Segment */}
              <div className="flex flex-wrap items-center gap-2">
                {seg.words.map((word, wordIdx) => {
                  const isWordActive =
                    state.currentTime >= word.start && state.currentTime <= word.end
                  const isWordSelected =
                    state.selectedSegmentIndex === segIdx && state.selectedWordIndex === wordIdx

                  return (
                    <div
                      key={word.id || `word-${wordIdx}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        dispatch({
                          type: 'SELECT_WORD',
                          payload: { segmentIndex: segIdx, wordIndex: wordIdx },
                        })
                      }}
                      className={`group relative flex flex-col p-2 rounded-lg border transition-all cursor-pointer ${
                        isWordActive
                          ? 'bg-cyan-500 text-gray-950 border-cyan-400 shadow-md font-bold scale-105'
                          : isWordSelected
                          ? 'bg-gray-800 text-cyan-300 border-cyan-500/80 shadow'
                          : 'bg-gray-800/80 text-gray-200 border-gray-700 hover:border-gray-600'
                      }`}
                    >
                      {/* Word Text (or Input when editing) */}
                      <div className="flex items-center justify-between gap-1.5">
                        {editingWordId === word.id ? (
                          <input
                            type="text"
                            value={editingText}
                            autoFocus
                            onChange={(e) => setEditingText(e.target.value)}
                            onBlur={() => handleSaveEditText(segIdx, wordIdx)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleSaveEditText(segIdx, wordIdx)
                              if (e.key === 'Escape') setEditingWordId(null)
                            }}
                            className="bg-black/80 text-white font-medium px-1.5 py-0.5 rounded text-sm w-24 focus:outline-none border border-cyan-400"
                          />
                        ) : (
                          <span className="text-sm font-semibold tracking-wide">
                            {word.text}
                          </span>
                        )}

                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleStartEditText(word.id, word.text)
                          }}
                          title="Editar texto"
                          className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-cyan-400 transition-opacity"
                        >
                          <Edit2 className="w-3 h-3" />
                        </button>
                      </div>

                      {/* Timestamps & Micro Adjustments */}
                      <div className="flex items-center justify-between gap-2 mt-1 pt-1 border-t border-black/10 text-[10px] font-mono opacity-80">
                        <span>{word.start.toFixed(2)}s</span>
                        <span>{word.end.toFixed(2)}s</span>
                      </div>

                      {/* Micro shift hover bar */}
                      <div
                        className="opacity-0 group-hover:opacity-100 flex items-center justify-center gap-1 mt-1 pt-1 border-t border-gray-700/50 transition-opacity"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          onClick={() =>
                            dispatch({
                              type: 'SHIFT_WORD',
                              payload: { segmentIndex: segIdx, wordIndex: wordIdx, delta: -0.05 },
                            })
                          }
                          title="Mover palabra -50ms"
                          className="p-1 bg-black/40 hover:bg-black/80 rounded text-[10px]"
                        >
                          <MoveLeft className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() =>
                            dispatch({
                              type: 'SHIFT_WORD',
                              payload: { segmentIndex: segIdx, wordIndex: wordIdx, delta: 0.05 },
                            })
                          }
                          title="Mover palabra +50ms"
                          className="p-1 bg-black/40 hover:bg-black/80 rounded text-[10px]"
                        >
                          <MoveRight className="w-3 h-3" />
                        </button>
                        <button
                          onClick={() =>
                            dispatch({
                              type: 'DELETE_WORD',
                              payload: { segmentIndex: segIdx, wordIndex: wordIdx },
                            })
                          }
                          title="Eliminar palabra"
                          className="p-1 text-red-400 hover:text-red-300 hover:bg-black/80 rounded text-[10px]"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  )
                })}

                {/* Add Word Button */}
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    handleAddWordPrompt(segIdx, seg.words.length - 1)
                  }}
                  title="Agregar palabra a este segmento"
                  className="flex items-center gap-1 px-2 py-1.5 bg-gray-800/50 hover:bg-gray-700 text-gray-400 hover:text-cyan-300 border border-dashed border-gray-700 hover:border-cyan-500/50 rounded-lg text-xs transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Palabra
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
