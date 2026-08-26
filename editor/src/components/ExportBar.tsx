import { useState } from 'react'
import type { FC } from 'react'
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ClipboardCopy,
  Download,
  FileCode,
  FileJson,
  Terminal,
} from 'lucide-react'
import { generateAss } from '../domain/assGenerator'
import type { EditorState } from '../state/editorReducer'

interface Props {
  state: EditorState
}

export const ExportBar: FC<Props> = ({ state }) => {
  const [copied, setCopied] = useState(false)
  const { transcript, style, validationErrors } = state

  if (!transcript) return null

  const errors = validationErrors.filter((e) => e.type === 'error')
  const warnings = validationErrors.filter((e) => e.type === 'warning')
  const isBlocked = errors.length > 0

  const safeTitle = (transcript.song.title || 'karaoke')
    .replace(/[^\w.-]+/g, '_')
    .slice(0, 50)

  const downloadFile = (content: string, filename: string, mimeType: string) => {
    const blob = new Blob([content], { type: mimeType })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const handleExportJson = () => {
    const jsonStr = JSON.stringify(transcript, null, 2)
    downloadFile(jsonStr, `${safeTitle}_edited_transcript.json`, 'application/json')
  }

  const handleExportAss = () => {
    const assStr = generateAss(transcript, style)
    downloadFile(assStr, `${safeTitle}_edited_karaoke.ass`, 'text/plain')
  }

  const handleCopyAss = () => {
    const assStr = generateAss(transcript, style)
    navigator.clipboard.writeText(assStr)
    setCopied(true)
    setTimeout(() => setCopied(false), 2500)
  }

  return (
    <div className="flex flex-col gap-6 bg-gray-900 border border-gray-800 p-6 rounded-xl">
      {/* Validation Status */}
      <div className="flex flex-col gap-3">
        <h3 className="text-lg font-bold text-white flex items-center gap-2">
          <Download className="w-5 h-5 text-cyan-400" />
          Exportación y Verificación de Integridad
        </h3>

        {/* Status Box */}
        {isBlocked ? (
          <div className="p-4 bg-red-950/40 border border-red-800 rounded-lg text-sm text-red-200">
            <div className="flex items-center gap-2 font-bold text-red-400 mb-2">
              <AlertCircle className="w-4 h-4" />
              {errors.length} Errores de Validación Bloqueantes
            </div>
            <ul className="list-disc list-inside space-y-1 text-xs text-red-300">
              {errors.map((err, idx) => (
                <li key={idx}>
                  {err.message} {err.field ? `(${err.field})` : ''}
                </li>
              ))}
            </ul>
          </div>
        ) : warnings.length > 0 ? (
          <div className="p-4 bg-amber-950/40 border border-amber-800 rounded-lg text-sm text-amber-200">
            <div className="flex items-center gap-2 font-bold text-amber-400 mb-2">
              <AlertTriangle className="w-4 h-4" />
              {warnings.length} Advertencias detectadas (no bloqueantes)
            </div>
            <ul className="list-disc list-inside space-y-1 text-xs text-amber-300">
              {warnings.map((warn, idx) => (
                <li key={idx}>
                  {warn.message} {warn.field ? `(${warn.field})` : ''}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="flex items-center gap-2 p-3 bg-emerald-950/40 border border-emerald-800 rounded-lg text-sm text-emerald-300 font-medium">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            Todos los invariantes de timing, IDs y timestamps son válidos y consistentes.
          </div>
        )}
      </div>

      {/* Export Action Buttons */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <button
          onClick={handleExportJson}
          disabled={isBlocked}
          className="flex flex-col items-center justify-center p-4 bg-gray-800 hover:bg-gray-750 disabled:opacity-40 disabled:hover:bg-gray-800 border border-gray-700 rounded-xl transition-all group text-left"
        >
          <div className="flex items-center gap-2 text-cyan-400 font-bold mb-1">
            <FileJson className="w-5 h-5" />
            <span>Descargar Transcript JSON</span>
          </div>
          <span className="text-xs text-gray-400 text-center">
            {safeTitle}_edited_transcript.json
          </span>
        </button>

        <button
          onClick={handleExportAss}
          disabled={isBlocked}
          className="flex flex-col items-center justify-center p-4 bg-cyan-600/20 hover:bg-cyan-600/30 disabled:opacity-40 disabled:hover:bg-cyan-600/20 border border-cyan-500/50 rounded-xl transition-all group text-left"
        >
          <div className="flex items-center gap-2 text-cyan-300 font-bold mb-1">
            <FileCode className="w-5 h-5" />
            <span>Descargar Subtítulos ASS</span>
          </div>
          <span className="text-xs text-cyan-400/80 text-center">
            {safeTitle}_edited_karaoke.ass
          </span>
        </button>

        <button
          onClick={handleCopyAss}
          disabled={isBlocked}
          className="flex flex-col items-center justify-center p-4 bg-gray-800 hover:bg-gray-750 disabled:opacity-40 disabled:hover:bg-gray-800 border border-gray-700 rounded-xl transition-all group text-left"
        >
          <div className="flex items-center gap-2 text-purple-400 font-bold mb-1">
            <ClipboardCopy className="w-5 h-5" />
            <span>{copied ? '¡Copiado al Portapapeles!' : 'Copiar ASS al Portapapeles'}</span>
          </div>
          <span className="text-xs text-gray-400 text-center">Formato ASS v4.00+</span>
        </button>
      </div>

      {/* Usage with CLI Instructions */}
      <div className="bg-gray-850 p-4 rounded-xl border border-gray-800 flex flex-col gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-300">
          <Terminal className="w-4 h-4 text-cyan-400" />
          <span>¿Cómo renderizar el video con los subtítulos editados?</span>
        </div>
        <p className="text-xs text-gray-400">
          Puedes renderizar directamente en tu máquina local usando <code className="text-cyan-300">ffmpeg</code> con el archivo ASS descargado:
        </p>
        <pre className="bg-black/60 p-3 rounded-lg text-xs font-mono text-gray-300 overflow-x-auto border border-white/5">
          {`ffmpeg -y -loop 1 -i background.png -i instrumental.flac -vf "ass=${safeTitle}_edited_karaoke.ass" -c:v libx264 -preset medium -c:a aac -b:a 192k -shortest output_karaoke.mp4`}
        </pre>
      </div>
    </div>
  )
}
