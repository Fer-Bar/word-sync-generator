import { useMemo } from 'react'
import type { Dispatch, FC } from 'react'
import { Eye, Sparkles } from 'lucide-react'
import { buildLyricPages } from '../domain/assGenerator'
import type { EditorAction, EditorState } from '../state/editorReducer'

interface Props {
  state: EditorState
  dispatch: Dispatch<EditorAction>
}

export const LivePreview: FC<Props> = ({ state, dispatch }) => {
  const { transcript, style, currentTime } = state

  const pages = useMemo(() => {
    if (!transcript) return []
    return buildLyricPages(transcript.segments)
  }, [transcript])

  // Find the page active at current time (in centiseconds)
  const currentCs = Math.round(currentTime * 100)
  const activePage = useMemo(() => {
    if (!pages.length) return null
    return (
      pages.find((p) => currentCs >= p.display_start_cs && currentCs <= p.display_end_cs) ||
      pages.find((p) => currentCs < p.display_start_cs) ||
      pages[pages.length - 1]
    )
  }, [pages, currentCs])

  const textStrokeStyle = useMemo(() => {
    const outlineWidth = style.outlineWidth
    const outlineColor = style.outlineColor
    const shadowWidth = style.shadowWidth
    const shadowAlpha = (style.shadowAlpha / 255).toFixed(2)

    return {
      WebkitTextStroke: outlineWidth > 0 ? `${outlineWidth * 0.7}px ${outlineColor}` : 'none',
      textShadow:
        shadowWidth > 0
          ? `${shadowWidth * 2}px ${shadowWidth * 2}px 4px rgba(0,0,0,${shadowAlpha})`
          : 'none',
      fontFamily: style.fontFamily,
      fontWeight: style.bold ? 700 : 400,
      fontStyle: style.italic ? 'italic' : 'normal',
    }
  }, [style])

  return (
    <div className="flex flex-col gap-4">
      {/* 16:9 Video Canvas Frame */}
      <div
        className="relative w-full aspect-video rounded-2xl overflow-hidden shadow-2xl border border-gray-800 flex items-center justify-center select-none"
        style={{
          backgroundColor:
            style.backgroundKind === 'solid' ? style.backgroundColor : '#0B1020',
        }}
      >
        {/* Background Image if uploaded */}
        {style.backgroundKind === 'image' && style.backgroundImageUrl && (
          <>
            <img
              src={style.backgroundImageUrl}
              alt="Video Background"
              className="absolute inset-0 w-full h-full object-cover"
            />
            {/* Dark overlay matching ffmpeg filter: black@0.38 */}
            <div className="absolute inset-0 bg-black/40" />
          </>
        )}

        {/* Resolution Watermark */}
        <div className="absolute top-4 left-4 z-10 flex items-center gap-2 px-2.5 py-1 bg-black/60 backdrop-blur-md rounded-lg text-[11px] font-mono text-cyan-300 border border-white/10">
          <Eye className="w-3.5 h-3.5" />
          <span>
            {style.videoWidth}x{style.videoHeight} • Live ASS Preview
          </span>
        </div>

        {/* Current Time Clock Overlay */}
        <div className="absolute top-4 right-4 z-10 px-2.5 py-1 bg-black/60 backdrop-blur-md rounded-lg text-[11px] font-mono text-gray-300 border border-white/10">
          {currentTime.toFixed(2)}s
        </div>

        {/* Rendered Lyrics Overlay */}
        <div
          className="relative z-10 w-full h-full flex flex-col justify-center px-12 transition-all duration-150"
          style={{
            justifyContent:
              style.alignment === 8
                ? 'flex-start'
                : style.alignment === 2
                ? 'flex-end'
                : 'center',
            paddingTop: style.alignment === 8 ? `${style.marginV}px` : '40px',
            paddingBottom: style.alignment === 2 ? `${style.marginV}px` : '40px',
          }}
        >
          {activePage ? (
            <div className="flex flex-col items-center gap-4 text-center">
              {activePage.lines.map((line, lIdx) => (
                <div
                  key={line.id || `line-${lIdx}`}
                  className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 leading-tight transition-transform duration-200"
                >
                  {line.words.map((word, wIdx) => {
                    const isSung = currentTime >= word.end
                    const isSinging = currentTime >= word.start && currentTime < word.end

                    // Progress inside the word for fluid fill animation
                    const progress = isSinging
                      ? Math.min(
                          1,
                          Math.max(0, (currentTime - word.start) / Math.max(0.05, word.end - word.start))
                        )
                      : isSung
                      ? 1
                      : 0

                    return (
                      <span
                        key={word.id || `word-${wIdx}`}
                        onClick={() =>
                          dispatch({
                            type: 'SET_CURRENT_TIME',
                            payload: Math.max(0, word.start - 0.1),
                          })
                        }
                        title={`Timestamp: ${word.start}s - ${word.end}s (Click para saltar)`}
                        className={`relative cursor-pointer transition-all duration-100 ${
                          isSinging ? 'scale-110 font-black' : ''
                        }`}
                        style={{
                          fontSize: `clamp(20px, ${style.fontSize * 0.045}vw, ${style.fontSize}px)`,
                          ...textStrokeStyle,
                        }}
                      >
                        {/* Base Text (Secondary / Unsung color) */}
                        <span
                          style={{
                            color: style.secondaryColor,
                          }}
                        >
                          {word.text}
                        </span>

                        {/* Animated Overlay Text (Primary / Sung color) */}
                        {(isSinging || isSung) && (
                          <span
                            className="absolute left-0 top-0 overflow-hidden whitespace-nowrap select-none pointer-events-none"
                            style={{
                              width: `${progress * 100}%`,
                              color: style.primaryColor,
                              filter: isSinging
                                ? `drop-shadow(0 0 8px ${style.primaryColor})`
                                : 'none',
                            }}
                          >
                            {word.text}
                          </span>
                        )}
                      </span>
                    )
                  })}
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center text-center text-gray-500 gap-2">
              <Sparkles className="w-8 h-8 opacity-40 animate-pulse text-cyan-400" />
              <p className="text-sm font-medium">
                {transcript ? 'Esperando inicio de letra...' : 'Carga un transcript para ver la previsualización'}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
