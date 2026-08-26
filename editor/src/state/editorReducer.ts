import { DEFAULT_STYLE_CONFIG } from '../domain/assGenerator'
import { addWord, deleteWord, shiftSegment, shiftWord, updateWord } from '../domain/timing'
import { validateTranscript } from '../domain/transcript'
import type { StyleConfig, Transcript, ValidationError, Word } from '../domain/types'

export interface EditorState {
  transcript: Transcript | null
  originalTranscript: Transcript | null
  style: StyleConfig
  mediaUrl: string | null
  mediaName: string | null
  mediaType: 'video' | 'audio' | null
  currentTime: number
  isPlaying: boolean
  playbackRate: number
  selectedSegmentIndex: number | null
  selectedWordIndex: number | null
  validationErrors: ValidationError[]
  history: Transcript[]
  future: Transcript[]
  activeTab: 'lyrics' | 'styles' | 'preview' | 'export'
}

export const initialState: EditorState = {
  transcript: null,
  originalTranscript: null,
  style: DEFAULT_STYLE_CONFIG,
  mediaUrl: null,
  mediaName: null,
  mediaType: null,
  currentTime: 0,
  isPlaying: false,
  playbackRate: 1.0,
  selectedSegmentIndex: null,
  selectedWordIndex: null,
  validationErrors: [],
  history: [],
  future: [],
  activeTab: 'lyrics',
}

export type EditorAction =
  | { type: 'LOAD_TRANSCRIPT'; payload: Transcript }
  | { type: 'LOAD_MEDIA'; payload: { url: string; name: string; type: 'video' | 'audio' } }
  | { type: 'CLEAR_MEDIA' }
  | { type: 'SET_CURRENT_TIME'; payload: number }
  | { type: 'SET_PLAYING'; payload: boolean }
  | { type: 'SET_PLAYBACK_RATE'; payload: number }
  | { type: 'SELECT_SEGMENT'; payload: number | null }
  | { type: 'SELECT_WORD'; payload: { segmentIndex: number | null; wordIndex: number | null } }
  | { type: 'SHIFT_WORD'; payload: { segmentIndex: number; wordIndex: number; delta: number } }
  | { type: 'SHIFT_SEGMENT'; payload: { segmentIndex: number; delta: number } }
  | {
      type: 'UPDATE_WORD'
      payload: {
        segmentIndex: number
        wordIndex: number
        updates: Partial<Pick<Word, 'text' | 'start' | 'end'>>
      }
    }
  | { type: 'ADD_WORD'; payload: { segmentIndex: number; afterWordIndex: number; text: string } }
  | { type: 'DELETE_WORD'; payload: { segmentIndex: number; wordIndex: number } }
  | { type: 'UPDATE_STYLE'; payload: Partial<StyleConfig> }
  | { type: 'RESET_STYLE' }
  | { type: 'UNDO' }
  | { type: 'REDO' }
  | { type: 'SET_TAB'; payload: 'lyrics' | 'styles' | 'preview' | 'export' }

function pushHistory(state: EditorState, newTranscript: Transcript): Partial<EditorState> {
  const history = state.transcript ? [...state.history.slice(-20), state.transcript] : state.history
  const errors = validateTranscript(newTranscript)
  return {
    transcript: newTranscript,
    validationErrors: errors,
    history,
    future: [],
  }
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case 'LOAD_TRANSCRIPT': {
      const errors = validateTranscript(action.payload)
      return {
        ...state,
        transcript: action.payload,
        originalTranscript: action.payload,
        validationErrors: errors,
        history: [],
        future: [],
        selectedSegmentIndex: 0,
        selectedWordIndex: 0,
      }
    }

    case 'LOAD_MEDIA':
      return {
        ...state,
        mediaUrl: action.payload.url,
        mediaName: action.payload.name,
        mediaType: action.payload.type,
      }

    case 'CLEAR_MEDIA':
      return {
        ...state,
        mediaUrl: null,
        mediaName: null,
        mediaType: null,
      }

    case 'SET_CURRENT_TIME':
      return { ...state, currentTime: action.payload }

    case 'SET_PLAYING':
      return { ...state, isPlaying: action.payload }

    case 'SET_PLAYBACK_RATE':
      return { ...state, playbackRate: action.payload }

    case 'SELECT_SEGMENT':
      return {
        ...state,
        selectedSegmentIndex: action.payload,
        selectedWordIndex: null,
      }

    case 'SELECT_WORD':
      return {
        ...state,
        selectedSegmentIndex: action.payload.segmentIndex,
        selectedWordIndex: action.payload.wordIndex,
      }

    case 'SHIFT_WORD': {
      if (!state.transcript) return state
      const updated = shiftWord(
        state.transcript,
        action.payload.segmentIndex,
        action.payload.wordIndex,
        action.payload.delta
      )
      return { ...state, ...pushHistory(state, updated) }
    }

    case 'SHIFT_SEGMENT': {
      if (!state.transcript) return state
      const updated = shiftSegment(state.transcript, action.payload.segmentIndex, action.payload.delta)
      return { ...state, ...pushHistory(state, updated) }
    }

    case 'UPDATE_WORD': {
      if (!state.transcript) return state
      const updated = updateWord(
        state.transcript,
        action.payload.segmentIndex,
        action.payload.wordIndex,
        action.payload.updates
      )
      return { ...state, ...pushHistory(state, updated) }
    }

    case 'ADD_WORD': {
      if (!state.transcript) return state
      const updated = addWord(
        state.transcript,
        action.payload.segmentIndex,
        action.payload.afterWordIndex,
        action.payload.text
      )
      return { ...state, ...pushHistory(state, updated) }
    }

    case 'DELETE_WORD': {
      if (!state.transcript) return state
      const updated = deleteWord(
        state.transcript,
        action.payload.segmentIndex,
        action.payload.wordIndex
      )
      return { ...state, ...pushHistory(state, updated) }
    }

    case 'UPDATE_STYLE':
      return {
        ...state,
        style: { ...state.style, ...action.payload },
      }

    case 'RESET_STYLE':
      return {
        ...state,
        style: DEFAULT_STYLE_CONFIG,
      }

    case 'UNDO': {
      if (state.history.length === 0 || !state.transcript) return state
      const previous = state.history[state.history.length - 1]
      const newHistory = state.history.slice(0, -1)
      const errors = validateTranscript(previous)
      return {
        ...state,
        transcript: previous,
        validationErrors: errors,
        history: newHistory,
        future: [state.transcript, ...state.future],
      }
    }

    case 'REDO': {
      if (state.future.length === 0 || !state.transcript) return state
      const next = state.future[0]
      const newFuture = state.future.slice(1)
      const errors = validateTranscript(next)
      return {
        ...state,
        transcript: next,
        validationErrors: errors,
        history: [...state.history, state.transcript],
        future: newFuture,
      }
    }

    case 'SET_TAB':
      return { ...state, activeTab: action.payload }

    default:
      return state
  }
}
