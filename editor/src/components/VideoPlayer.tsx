import { useEffect, useRef, useState } from 'react'
import type { Dispatch, FC, RefObject } from 'react'
import {
  FastForward,
  Gauge,
  Pause,
  Play,
  Repeat,
  RotateCcw,
  Volume2,
  VolumeX,
} from 'lucide-react'
import type { EditorAction, EditorState } from '../state/editorReducer'

interface Props {
  state: EditorState
  dispatch: Dispatch<EditorAction>
}

export const VideoPlayer: FC<Props> = ({ state, dispatch }) => {
  const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null)
  const animFrameRef = useRef<number | null>(null)
  const isPlayingRef = useRef<boolean>(state.isPlaying)
  const loopSegmentRef = useRef<boolean>(false)
  const currentTimeRef = useRef<number>(state.currentTime)
  const [isMuted, setIsMuted] = useState(false)
  const [loopSegment, setLoopSegment] = useState(false)

  useEffect(() => {
    loopSegmentRef.current = loopSegment
  }, [loopSegment])

  useEffect(() => {
    isPlayingRef.current = state.isPlaying
  }, [state.isPlaying])

  useEffect(() => {
    currentTimeRef.current = state.currentTime
  }, [state.currentTime])

  // Animation frame ticker for ultra-smooth timestamp tracking
  useEffect(() => {
    let lastStamp = performance.now()

    const updateLoop = () => {
      if (isPlayingRef.current) {
        if (mediaRef.current) {
          const current = mediaRef.current.currentTime
          dispatch({ type: 'SET_CURRENT_TIME', payload: current })

          // Handle loop segment
          if (loopSegmentRef.current && state.selectedSegmentIndex !== null && state.transcript) {
            const seg = state.transcript.segments[state.selectedSegmentIndex]
            if (seg && current >= seg.end + 0.3) {
              mediaRef.current.currentTime = Math.max(0, seg.start - 0.2)
            }
          }
        } else {
          // Synthetic playback when no media file is attached
          const now = performance.now()
          const delta = ((now - lastStamp) / 1000) * state.playbackRate
          lastStamp = now
          const nextTime = currentTimeRef.current + delta
          dispatch({ type: 'SET_CURRENT_TIME', payload: nextTime })
        }
      }
      animFrameRef.current = requestAnimationFrame(updateLoop)
    }

    animFrameRef.current = requestAnimationFrame(updateLoop)
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current)
    }
  }, [state.playbackRate, state.selectedSegmentIndex, state.transcript, dispatch])

  // Sync isPlaying state with HTML5 media element
  useEffect(() => {
    if (!mediaRef.current) return
    if (state.isPlaying && mediaRef.current.paused) {
      mediaRef.current.play().catch(() => {})
    } else if (!state.isPlaying && !mediaRef.current.paused) {
      mediaRef.current.pause()
    }
  }, [state.isPlaying])

  // Sync playback rate
  useEffect(() => {
    if (mediaRef.current) {
      mediaRef.current.playbackRate = state.playbackRate
    }
  }, [state.playbackRate])

  const togglePlay = () => {
    dispatch({ type: 'SET_PLAYING', payload: !state.isPlaying })
  }

  const handleSeek = (newTime: number) => {
    const boundedTime = Math.max(0, newTime)
    if (mediaRef.current) {
      mediaRef.current.currentTime = boundedTime
    }
    dispatch({ type: 'SET_CURRENT_TIME', payload: boundedTime })
  }

  const jumpRelative = (deltaSeconds: number) => {
    handleSeek(state.currentTime + deltaSeconds)
  }

  const jumpToSegment = (segIdx: number) => {
    if (!state.transcript || segIdx < 0 || segIdx >= state.transcript.segments.length) return
    const seg = state.transcript.segments[segIdx]
    handleSeek(Math.max(0, seg.start - 0.2))
  }

  const formatClock = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    const ms = Math.floor((seconds % 1) * 1000)
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(ms).padStart(3, '0')}`
  }

  const totalDuration =
    state.transcript?.song.duration ||
    (state.transcript?.segments.length
      ? state.transcript.segments[state.transcript.segments.length - 1].end + 5
      : 60)

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 shadow-lg flex flex-col gap-3">
      {/* Hidden or visible media element */}
      {state.mediaUrl && (
        <div className="relative rounded-lg overflow-hidden bg-black/80 flex items-center justify-center max-h-48">
          {state.mediaType === 'video' ? (
            <video
              ref={mediaRef as RefObject<HTMLVideoElement>}
              src={state.mediaUrl}
              className="w-full max-h-48 object-contain"
              muted={isMuted}
              onEnded={() => dispatch({ type: 'SET_PLAYING', payload: false })}
            />
          ) : (
            <audio
              ref={mediaRef as RefObject<HTMLAudioElement>}
              src={state.mediaUrl}
              muted={isMuted}
              onEnded={() => dispatch({ type: 'SET_PLAYING', payload: false })}
            />
          )}
        </div>
      )}

      {/* Scrubber Timeline */}
      <div className="flex flex-col gap-1">
        <div className="flex justify-between text-xs font-mono text-gray-400">
          <span className="text-cyan-400 font-semibold">{formatClock(state.currentTime)}</span>
          <span>{formatClock(totalDuration)}</span>
        </div>
        <input
          type="range"
          min="0"
          max={totalDuration}
          step="0.01"
          value={state.currentTime}
          onChange={(e) => handleSeek(parseFloat(e.target.value))}
          className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-cyan-400 hover:bg-gray-600 transition-colors"
        />
      </div>

      {/* Control Buttons */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
        <div className="flex items-center gap-2">
          <button
            onClick={() => jumpRelative(-2)}
            title="Retroceder 2s"
            className="p-2 text-gray-300 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
          >
            <RotateCcw className="w-4 h-4" />
          </button>

          <button
            onClick={togglePlay}
            title={state.isPlaying ? 'Pausa (Espacio)' : 'Reproducir (Espacio)'}
            className="p-3 bg-cyan-500 hover:bg-cyan-400 text-gray-950 font-bold rounded-full shadow-md transition-transform active:scale-95 flex items-center justify-center"
          >
            {state.isPlaying ? (
              <Pause className="w-5 h-5 fill-current" />
            ) : (
              <Play className="w-5 h-5 fill-current ml-0.5" />
            )}
          </button>

          <button
            onClick={() => jumpRelative(2)}
            title="Avanzar 2s"
            className="p-2 text-gray-300 hover:text-white hover:bg-gray-800 rounded-lg transition-colors"
          >
            <FastForward className="w-4 h-4" />
          </button>

          <button
            onClick={() => setLoopSegment(!loopSegment)}
            title={loopSegment ? 'Bucle de segmento activado' : 'Repetir segmento seleccionado'}
            className={`p-2 rounded-lg transition-colors ${
              loopSegment
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
            }`}
          >
            <Repeat className="w-4 h-4" />
          </button>
        </div>

        {/* Speed and Volume Controls */}
        <div className="flex items-center gap-3">
          {state.selectedSegmentIndex !== null && (
            <button
              onClick={() => jumpToSegment(state.selectedSegmentIndex!)}
              className="text-xs px-2.5 py-1.5 bg-gray-800 hover:bg-gray-700 text-cyan-300 rounded border border-gray-700 transition-colors"
            >
              Ir a Segmento {state.selectedSegmentIndex + 1}
            </button>
          )}

          {/* Speed Selector */}
          <div className="flex items-center gap-1 bg-gray-800 px-2 py-1 rounded-lg border border-gray-700 text-xs">
            <Gauge className="w-3.5 h-3.5 text-gray-400" />
            <select
              value={state.playbackRate}
              onChange={(e) =>
                dispatch({ type: 'SET_PLAYBACK_RATE', payload: parseFloat(e.target.value) })
              }
              className="bg-transparent text-gray-200 focus:outline-none cursor-pointer"
            >
              <option value="0.5" className="bg-gray-900">
                0.5x
              </option>
              <option value="0.75" className="bg-gray-900">
                0.75x
              </option>
              <option value="1" className="bg-gray-900">
                1.0x (Normal)
              </option>
              <option value="1.25" className="bg-gray-900">
                1.25x
              </option>
              <option value="1.5" className="bg-gray-900">
                1.5x
              </option>
            </select>
          </div>

          {state.mediaUrl && (
            <button
              onClick={() => setIsMuted(!isMuted)}
              title={isMuted ? 'Activar sonido' : 'Silenciar'}
              className="p-2 text-gray-400 hover:text-gray-200 hover:bg-gray-800 rounded-lg transition-colors"
            >
              {isMuted ? <VolumeX className="w-4 h-4 text-red-400" /> : <Volume2 className="w-4 h-4" />}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
