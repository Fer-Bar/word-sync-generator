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

      {/* Main Studio Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 flex flex-col gap-6">
        {/* File Ingestion Bar (Audio & JSON First) */}
        <FileLoader state={state} dispatch={dispatch} />

        {/* Studio Upper Deck: Live ASS Preview & Media Player / Scrubber */}
        <section className="bg-gray-900/90 border border-gray-800 rounded-2xl p-4 sm:p-5 shadow-2xl backdrop-blur-sm flex flex-col gap-4">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-center">
            {/* 16:9 Live Preview Canvas */}
            <div className="lg:col-span-7 xl:col-span-8 flex flex-col justify-center">
              <LivePreview state={state} dispatch={dispatch} />
            </div>

            {/* Transport Deck & Scrubber Controls */}
            <div className="lg:col-span-5 xl:col-span-4 flex flex-col justify-center h-full">
              <VideoPlayer state={state} dispatch={dispatch} />
            </div>
          </div>
        </section>

        {/* Studio Lower Deck: Interactive Workspace (Full-Width Lyrics Timeline / Styles / Export) */}
        <section className="flex flex-col gap-4">
          {state.activeTab === 'lyrics' && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between px-1">
                <h3 className="text-sm font-bold uppercase tracking-wider text-cyan-400 flex items-center gap-2">
                  <SlidersHorizontal className="w-4 h-4" />
                  Línea de Tiempo y Sincronización de Letras (Click-to-Seek)
                </h3>
                <span className="text-xs text-gray-400">
                  Haz clic en cualquier palabra para saltar el audio • Doble clic para editar texto
                </span>
              </div>
              <LyricsEditor state={state} dispatch={dispatch} />
            </div>
          )}

          {state.activeTab === 'styles' && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between px-1">
                <h3 className="text-sm font-bold uppercase tracking-wider text-cyan-400 flex items-center gap-2">
                  <Palette className="w-4 h-4" />
                  Personalización Visual: Colores, Tipografías y Fondo
                </h3>
              </div>
              <StyleEditor state={state} dispatch={dispatch} />
            </div>
          )}

          {state.activeTab === 'preview' && (
            <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl flex flex-col gap-4">
              <h3 className="text-lg font-bold text-white flex items-center gap-2">
                <Eye className="w-5 h-5 text-cyan-400" />
                Previsualización en Pantalla Completa
              </h3>
              <LivePreview state={state} dispatch={dispatch} />
            </div>
          )}

          {state.activeTab === 'export' && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between px-1">
                <h3 className="text-sm font-bold uppercase tracking-wider text-cyan-400 flex items-center gap-2">
                  <Download className="w-4 h-4" />
                  Exportación de Subtítulos ASS y Transcript JSON
                </h3>
              </div>
              <ExportBar state={state} />
            </div>
          )}
        </section>
      </main>
    </div>
  )
}

export default App
