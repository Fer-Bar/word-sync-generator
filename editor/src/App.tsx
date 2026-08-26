import { useReducer } from 'react'
import {
  Download,
  Eye,
  Music,
  Palette,
  SlidersHorizontal,
} from 'lucide-react'
import { ExportBar } from './components/ExportBar'
import { FileLoader } from './components/FileLoader'
import { LivePreview } from './components/LivePreview'
import { LyricsEditor } from './components/LyricsEditor'
import { StyleEditor } from './components/StyleEditor'
import { VideoPlayer } from './components/VideoPlayer'
import { editorReducer, initialState } from './state/editorReducer'

export function App() {
  const [state, dispatch] = useReducer(editorReducer, initialState)

  return (
    <div className="min-h-screen bg-[#0b0f19] text-gray-100 flex flex-col">
      {/* Top Navbar */}
      <header className="sticky top-0 z-50 bg-gray-900/90 backdrop-blur-md border-b border-gray-800 px-6 py-3">
        <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-tr from-cyan-600 to-purple-600 rounded-xl shadow-lg shadow-cyan-500/20">
              <Music className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-base font-bold tracking-tight text-white m-0 p-0">
                Karaoke Timing & Style Studio
              </h1>
              <p className="text-xs text-gray-400 m-0">Editor de subtítulos ASS y sincronización de letras</p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="flex items-center gap-1 bg-gray-800/80 p-1 rounded-xl border border-gray-700/60">
            <button
              onClick={() => dispatch({ type: 'SET_TAB', payload: 'lyrics' })}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                state.activeTab === 'lyrics'
                  ? 'bg-cyan-500 text-gray-950 shadow-md'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'
              }`}
            >
              <SlidersHorizontal className="w-3.5 h-3.5" />
              Sincronizar Letras
            </button>

            <button
              onClick={() => dispatch({ type: 'SET_TAB', payload: 'styles' })}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                state.activeTab === 'styles'
                  ? 'bg-cyan-500 text-gray-950 shadow-md'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'
              }`}
            >
              <Palette className="w-3.5 h-3.5" />
              Estilos y Video
            </button>

            <button
              onClick={() => dispatch({ type: 'SET_TAB', payload: 'preview' })}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                state.activeTab === 'preview'
                  ? 'bg-cyan-500 text-gray-950 shadow-md'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'
              }`}
            >
              <Eye className="w-3.5 h-3.5" />
              Previsualización
            </button>

            <button
              onClick={() => dispatch({ type: 'SET_TAB', payload: 'export' })}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                state.activeTab === 'export'
                  ? 'bg-cyan-500 text-gray-950 shadow-md'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-700/50'
              }`}
            >
              <Download className="w-3.5 h-3.5" />
              Exportar ASS / JSON
            </button>
          </nav>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6 flex flex-col gap-6">
        {/* File Loader Header */}
        <FileLoader state={state} dispatch={dispatch} />

        {/* Two-Column Grid: Left (Video & Live Preview), Right (Active Workspace Tab) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Left Column: Player & Live Preview */}
          <div className="lg:col-span-5 flex flex-col gap-4 sticky top-20">
            <LivePreview state={state} dispatch={dispatch} />
            <VideoPlayer state={state} dispatch={dispatch} />
          </div>

          {/* Right Column: Tab View */}
          <div className="lg:col-span-7 flex flex-col gap-4">
            {state.activeTab === 'lyrics' && <LyricsEditor state={state} dispatch={dispatch} />}
            {state.activeTab === 'styles' && <StyleEditor state={state} dispatch={dispatch} />}
            {state.activeTab === 'preview' && (
              <div className="bg-gray-900 border border-gray-800 p-6 rounded-xl flex flex-col gap-4">
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <Eye className="w-5 h-5 text-cyan-400" />
                  Previsualización en Pantalla Completa
                </h3>
                <LivePreview state={state} dispatch={dispatch} />
              </div>
            )}
            {state.activeTab === 'export' && <ExportBar state={state} />}
          </div>
        </div>
      </main>
    </div>
  )
}

export default App
