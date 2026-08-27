import { useEffect, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { formatTimestamp } from '../domain/time'

interface Props {
  audioRef: RefObject<HTMLAudioElement | null>
  src: string | null
  durationHint: number
  loopRange: { start: number; end: number } | null
  onTimeChange: (time: number) => void
}

export function AudioTransport({ audioRef, src, durationHint, loopRange, onTimeChange }: Props) {
  const [duration, setDuration] = useState(durationHint)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackRate, setPlaybackRate] = useState(1)
  const outputRef = useRef<HTMLOutputElement>(null)
  const rangeRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    const sync = () => {
      const time = audio.currentTime
      if (outputRef.current) outputRef.current.value = formatTimestamp(time)
      if (rangeRef.current && document.activeElement !== rangeRef.current) {
        rangeRef.current.value = String(time)
      }
      onTimeChange(time)

      if (!audio.paused && loopRange && time >= loopRange.end) {
        audio.currentTime = loopRange.start
        void audio.play()
      }
    }
    const handlePlay = () => setIsPlaying(true)
    const handlePause = () => setIsPlaying(false)
    const handleMetadata = () => setDuration(audio.duration || durationHint)
    const handleEnded = () => {
      setIsPlaying(false)
      sync()
    }

    audio.addEventListener('play', handlePlay)
    audio.addEventListener('pause', handlePause)
    audio.addEventListener('loadedmetadata', handleMetadata)
    audio.addEventListener('ended', handleEnded)
    const timer = window.setInterval(sync, 33)
    sync()

    return () => {
      audio.removeEventListener('play', handlePlay)
      audio.removeEventListener('pause', handlePause)
      audio.removeEventListener('loadedmetadata', handleMetadata)
      audio.removeEventListener('ended', handleEnded)
      window.clearInterval(timer)
    }
  }, [audioRef, durationHint, loopRange, onTimeChange, src])

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = playbackRate
  }, [audioRef, playbackRate])

  const maxDuration = Math.max(1, duration || durationHint)

  const seek = (time: number) => {
    const audio = audioRef.current
    if (!audio) return
    audio.currentTime = Math.max(0, Math.min(maxDuration, time))
    onTimeChange(audio.currentTime)
  }

  const togglePlayback = () => {
    const audio = audioRef.current
    if (!audio || !src) return
    if (audio.paused) void audio.play()
    else audio.pause()
  }

  return (
    <section className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <audio ref={audioRef} src={src ?? undefined} preload="metadata" className="hidden" />
      <div className="flex flex-wrap items-center gap-2">
        <button className="primary-button" disabled={!src} onClick={togglePlayback}>
          {isPlaying ? 'Pause' : 'Play'}
        </button>
        <button className="editor-button" disabled={!src} onClick={() => seek((audioRef.current?.currentTime ?? 0) - 2)}>
          -2s
        </button>
        <button className="editor-button" disabled={!src} onClick={() => seek((audioRef.current?.currentTime ?? 0) + 2)}>
          +2s
        </button>
        <output ref={outputRef} className="min-w-24 font-mono text-sm text-cyan-300" aria-label="Current time">
          00:00.000
        </output>
        <span className="font-mono text-sm text-gray-500">/</span>
        <span className="font-mono text-sm text-gray-400">{formatTimestamp(maxDuration)}</span>
        <label className="ml-auto flex items-center gap-2 text-xs text-gray-400">
          Speed
          <select
            className="editor-input w-auto py-1"
            value={playbackRate}
            onChange={(event) => setPlaybackRate(Number(event.target.value))}
          >
            <option value="0.5">0.5x</option>
            <option value="0.75">0.75x</option>
            <option value="1">1x</option>
            <option value="1.25">1.25x</option>
          </select>
        </label>
      </div>
      <input
        ref={rangeRef}
        className="mt-3 w-full accent-cyan-400"
        type="range"
        min="0"
        max={maxDuration}
        step="0.001"
        defaultValue="0"
        disabled={!src}
        onChange={(event) => seek(Number(event.target.value))}
        aria-label="Audio position"
      />
      {!src ? <p className="m-0 mt-2 text-xs text-gray-500">Load the prepared job audio to begin.</p> : null}
    </section>
  )
}
