export interface SongMetadata {
  title: string
  uploader?: string | null
  duration?: number | null
}

export interface TranscriptionInfo {
  engine?: string
  model?: string
  language?: string
  language_probability?: number
}

export interface Word {
  id: string
  start: number
  end: number
  text: string
  probability?: number
  timing?: TimingFragment[]
}

export interface TimingFragment {
  id: string
  text: string
  start: number
  end: number
}

export interface Segment {
  id: string
  start: number
  end: number
  text: string
  words: Word[]
}

export interface Transcript {
  schema_version: number
  song: SongMetadata
  transcription?: TranscriptionInfo
  segments: Segment[]
}

export interface EditDocument {
  schema_version: 2
  revision: number
  transcript: Transcript
  media: {
    original_audio: string
    instrumental_audio: string
    original_transcript: string
  }
  video: { width: number; height: number; fps: number }
  background: { kind: 'solid' | 'image'; color: string; path?: string }
}

export interface StyleConfig {
  fontFamily: string
  fontSize: number
  bold: boolean
  italic: boolean
  primaryColor: string // Highlighted/Sung text (#RRGGBB)
  secondaryColor: string // Unhighlighted text (#RRGGBB)
  outlineColor: string // Outline (#RRGGBB)
  outlineWidth: number
  shadowColor: string // Shadow (#RRGGBB)
  shadowAlpha: number // 0-255
  shadowWidth: number
  alignment: number // ASS alignment (5 = center, 2 = bottom-center, 8 = top-center)
  marginV: number
  marginL: number
  marginR: number
  backgroundKind: 'solid' | 'image'
  backgroundColor: string
  backgroundImageUrl?: string
  videoWidth: number
  videoHeight: number
  videoFps: number
}

export interface LyricPage {
  lines: Segment[]
  start: number
  end: number
  display_start_cs: number
  display_end_cs: number
  word_starts_cs: number[]
  durations_cs: number[]
  karaoke_end_cs: number
}

export interface ValidationError {
  type: 'error' | 'warning'
  message: string
  segmentIndex?: number
  wordIndex?: number
  field?: string
}
