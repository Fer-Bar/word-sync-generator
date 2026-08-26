import { useRef } from 'react'
import type { ChangeEvent, Dispatch, FC } from 'react'
import {
  Bold,
  Image as ImageIcon,
  Italic,
  Palette,
  RotateCcw,
  Sliders,
  Type,
  Video,
} from 'lucide-react'
import type { StyleConfig } from '../domain/types'
import type { EditorAction, EditorState } from '../state/editorReducer'

interface Props {
  state: EditorState
  dispatch: Dispatch<EditorAction>
}

const POPULAR_FONTS = [
  'DejaVu Sans',
  'Inter',
  'Roboto',
  'Montserrat',
  'Poppins',
  'Bebas Neue',
  'Oswald',
  'Arial',
  'Impact',
  'Trebuchet MS',
  'Georgia',
]

const COLOR_PRESETS = [
  {
    name: 'Cyan Neón (Default)',
    primary: '#00D7FF',
    secondary: '#FFFFFF',
    outline: '#000000',
    bg: '#0B1020',
  },
  {
    name: 'Dorado Cálido',
    primary: '#FFD700',
    secondary: '#FFF8E7',
    outline: '#1F1500',
    bg: '#140E05',
  },
  {
    name: 'Rosa Synthwave',
    primary: '#FF2E93',
    secondary: '#E0E7FF',
    outline: '#1E002B',
    bg: '#12051E',
  },
  {
    name: 'Verde Esmeralda',
    primary: '#10B981',
    secondary: '#ECFDF5',
    outline: '#022C22',
    bg: '#021B15',
  },
  {
    name: 'Blanco Minimal',
    primary: '#E2E8F0',
    secondary: '#94A3B8',
    outline: '#000000',
    bg: '#090D16',
  },
]

export const StyleEditor: FC<Props> = ({ state, dispatch }) => {
  const bgImageInputRef = useRef<HTMLInputElement>(null)
  const { style } = state

  const handleUpdate = (updates: Partial<StyleConfig>) => {
    dispatch({ type: 'UPDATE_STYLE', payload: updates })
  }

  const handleBgImageUpload = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (event) => {
      const dataUrl = event.target?.result as string
      handleUpdate({
        backgroundKind: 'image',
        backgroundImageUrl: dataUrl,
      })
    }
    reader.readAsDataURL(file)
  }

  return (
    <div className="flex flex-col gap-6 bg-gray-900 border border-gray-800 p-6 rounded-xl">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <Palette className="w-5 h-5 text-cyan-400" />
          <h3 className="text-lg font-bold text-white">Personalización de Estilos y Video</h3>
        </div>
        <button
          onClick={() => dispatch({ type: 'RESET_STYLE' })}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 text-xs rounded-lg border border-gray-700 transition-colors"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          Restablecer Valores por Defecto
        </button>
      </div>

      {/* Preset Packs */}
      <div>
        <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Paletas de Color Rápidas
        </label>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
          {COLOR_PRESETS.map((preset) => (
            <button
              key={preset.name}
              onClick={() =>
                handleUpdate({
                  primaryColor: preset.primary,
                  secondaryColor: preset.secondary,
                  outlineColor: preset.outline,
                  backgroundColor: preset.bg,
                })
              }
              className="flex flex-col items-center p-2.5 bg-gray-800/80 hover:bg-gray-800 border border-gray-700 rounded-lg transition-all text-xs text-left group"
            >
              <div className="flex items-center gap-1 w-full mb-1.5">
                <span
                  className="w-4 h-4 rounded-full border border-black/30"
                  style={{ backgroundColor: preset.primary }}
                />
                <span
                  className="w-4 h-4 rounded-full border border-black/30"
                  style={{ backgroundColor: preset.secondary }}
                />
                <span
                  className="w-4 h-4 rounded-full border border-black/30 ml-auto"
                  style={{ backgroundColor: preset.bg }}
                />
              </div>
              <span className="text-gray-300 font-medium group-hover:text-cyan-300 transition-colors">
                {preset.name}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Font Settings */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-4 bg-gray-850 p-4 rounded-xl border border-gray-800">
          <div className="flex items-center gap-2 text-cyan-400 font-semibold text-sm">
            <Type className="w-4 h-4" />
            <span>Tipografía y Texto</span>
          </div>

          {/* Font Family */}
          <div>
            <label className="block text-xs text-gray-400 mb-1">Tipo de Fuente</label>
            <select
              value={style.fontFamily}
              onChange={(e) => handleUpdate({ fontFamily: e.target.value })}
              className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-cyan-500"
            >
              {POPULAR_FONTS.map((font) => (
                <option key={font} value={font} style={{ fontFamily: font }}>
                  {font}
                </option>
              ))}
            </select>
          </div>

          {/* Font Size & Weight */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>Tamaño ({style.fontSize}px)</span>
              </div>
              <input
                type="range"
                min="24"
                max="120"
                value={style.fontSize}
                onChange={(e) => handleUpdate({ fontSize: parseInt(e.target.value) })}
                className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-cyan-400"
              />
            </div>

            <div className="flex items-end gap-2">
              <button
                onClick={() => handleUpdate({ bold: !style.bold })}
                className={`flex-1 flex items-center justify-center gap-1 py-2 px-3 rounded-lg border text-xs font-semibold transition-colors ${
                  style.bold
                    ? 'bg-cyan-500/20 border-cyan-500 text-cyan-300'
                    : 'bg-gray-800 border-gray-700 text-gray-400'
                }`}
              >
                <Bold className="w-4 h-4" /> Negrita
              </button>
              <button
                onClick={() => handleUpdate({ italic: !style.italic })}
                className={`flex-1 flex items-center justify-center gap-1 py-2 px-3 rounded-lg border text-xs font-semibold transition-colors ${
                  style.italic
                    ? 'bg-cyan-500/20 border-cyan-500 text-cyan-300'
                    : 'bg-gray-800 border-gray-700 text-gray-400'
                }`}
              >
                <Italic className="w-4 h-4" /> Cursiva
              </button>
            </div>
          </div>

          {/* Colors */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Color Resaltado (Voz)</label>
              <div className="flex items-center gap-2 bg-gray-800 p-1.5 rounded-lg border border-gray-700">
                <input
                  type="color"
                  value={style.primaryColor}
                  onChange={(e) => handleUpdate({ primaryColor: e.target.value })}
                  className="w-8 h-8 rounded border-none cursor-pointer bg-transparent"
                />
                <span className="font-mono text-xs text-gray-300">{style.primaryColor}</span>
              </div>
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Color Base (No cantado)</label>
              <div className="flex items-center gap-2 bg-gray-800 p-1.5 rounded-lg border border-gray-700">
                <input
                  type="color"
                  value={style.secondaryColor}
                  onChange={(e) => handleUpdate({ secondaryColor: e.target.value })}
                  className="w-8 h-8 rounded border-none cursor-pointer bg-transparent"
                />
                <span className="font-mono text-xs text-gray-300">{style.secondaryColor}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Outline, Shadow & Background */}
        <div className="space-y-4 bg-gray-850 p-4 rounded-xl border border-gray-800">
          <div className="flex items-center gap-2 text-cyan-400 font-semibold text-sm">
            <Sliders className="w-4 h-4" />
            <span>Borde, Sombra y Fondo</span>
          </div>

          {/* Outline and Shadow */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>Grosor de Borde ({style.outlineWidth}px)</span>
              </div>
              <input
                type="range"
                min="0"
                max="10"
                value={style.outlineWidth}
                onChange={(e) => handleUpdate({ outlineWidth: parseInt(e.target.value) })}
                className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-cyan-400"
              />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">Color de Borde</label>
              <div className="flex items-center gap-2 bg-gray-800 p-1.5 rounded-lg border border-gray-700">
                <input
                  type="color"
                  value={style.outlineColor}
                  onChange={(e) => handleUpdate({ outlineColor: e.target.value })}
                  className="w-8 h-8 rounded border-none cursor-pointer bg-transparent"
                />
                <span className="font-mono text-xs text-gray-300">{style.outlineColor}</span>
              </div>
            </div>
          </div>

          {/* Background Settings */}
          <div className="space-y-2 pt-2 border-t border-gray-700/50">
            <label className="block text-xs font-medium text-gray-400">Tipo de Fondo</label>
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => handleUpdate({ backgroundKind: 'solid' })}
                className={`py-2 px-3 rounded-lg border text-xs font-semibold transition-colors ${
                  style.backgroundKind === 'solid'
                    ? 'bg-cyan-500/20 border-cyan-500 text-cyan-300'
                    : 'bg-gray-800 border-gray-700 text-gray-400'
                }`}
              >
                Color Sólido
              </button>

              <button
                onClick={() => bgImageInputRef.current?.click()}
                className={`flex items-center justify-center gap-1.5 py-2 px-3 rounded-lg border text-xs font-semibold transition-colors ${
                  style.backgroundKind === 'image'
                    ? 'bg-cyan-500/20 border-cyan-500 text-cyan-300'
                    : 'bg-gray-800 border-gray-700 text-gray-400'
                }`}
              >
                <ImageIcon className="w-4 h-4" />
                {style.backgroundImageUrl ? 'Cambiar Imagen' : 'Subir Imagen'}
              </button>
              <input
                type="file"
                ref={bgImageInputRef}
                accept="image/*"
                onChange={handleBgImageUpload}
                className="hidden"
              />
            </div>

            {style.backgroundKind === 'solid' && (
              <div className="flex items-center gap-2 bg-gray-800 p-1.5 rounded-lg border border-gray-700 mt-2">
                <input
                  type="color"
                  value={style.backgroundColor}
                  onChange={(e) => handleUpdate({ backgroundColor: e.target.value })}
                  className="w-8 h-8 rounded border-none cursor-pointer bg-transparent"
                />
                <span className="font-mono text-xs text-gray-300">
                  Color Fondo: {style.backgroundColor}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Video Resolution & Margins */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 bg-gray-850 p-4 rounded-xl border border-gray-800">
        <div>
          <label className="block text-xs text-gray-400 mb-1 flex items-center gap-1.5">
            <Video className="w-3.5 h-3.5 text-cyan-400" />
            Resolución
          </label>
          <select
            value={`${style.videoWidth}x${style.videoHeight}`}
            onChange={(e) => {
              const [w, h] = e.target.value.split('x').map(Number)
              handleUpdate({ videoWidth: w, videoHeight: h })
            }}
            className="w-full bg-gray-800 border border-gray-700 text-white rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-cyan-500"
          >
            <option value="1920x1080">1080p Full HD (1920 x 1080)</option>
            <option value="1280x720">720p HD (1280 x 720)</option>
            <option value="3840x2160">4K Ultra HD (3840 x 2160)</option>
          </select>
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1">Margen Vertical ({style.marginV}px)</label>
          <input
            type="range"
            min="20"
            max="200"
            value={style.marginV}
            onChange={(e) => handleUpdate({ marginV: parseInt(e.target.value) })}
            className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-cyan-400"
          />
        </div>

        <div>
          <label className="block text-xs text-gray-400 mb-1">Alineación ASS</label>
          <div className="flex gap-2">
            <button
              onClick={() => handleUpdate({ alignment: 8 })}
              className={`flex-1 py-1.5 rounded border text-xs ${
                style.alignment === 8
                  ? 'bg-cyan-500/20 border-cyan-500 text-cyan-300'
                  : 'bg-gray-800 border-gray-700 text-gray-400'
              }`}
            >
              Arriba (8)
            </button>
            <button
              onClick={() => handleUpdate({ alignment: 5 })}
              className={`flex-1 py-1.5 rounded border text-xs ${
                style.alignment === 5
                  ? 'bg-cyan-500/20 border-cyan-500 text-cyan-300'
                  : 'bg-gray-800 border-gray-700 text-gray-400'
              }`}
            >
              Centro (5)
            </button>
            <button
              onClick={() => handleUpdate({ alignment: 2 })}
              className={`flex-1 py-1.5 rounded border text-xs ${
                style.alignment === 2
                  ? 'bg-cyan-500/20 border-cyan-500 text-cyan-300'
                  : 'bg-gray-800 border-gray-700 text-gray-400'
              }`}
            >
              Abajo (2)
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
