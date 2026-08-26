import type { LyricPage, StyleConfig, Transcript, Word } from './types'

export const DEFAULT_STYLE_CONFIG: StyleConfig = {
  fontFamily: 'DejaVu Sans',
  fontSize: 64,
  bold: true,
  italic: false,
  primaryColor: '#00D7FF', // Highlighted/Sung text color
  secondaryColor: '#FFFFFF', // Unhighlighted text color
  outlineColor: '#000000',
  outlineWidth: 4,
  shadowColor: '#000000',
  shadowAlpha: 112, // &H70
  shadowWidth: 1,
  alignment: 5, // Center
  marginV: 70,
  marginL: 70,
  marginR: 70,
  backgroundKind: 'solid',
  backgroundColor: '#0B1020',
  videoWidth: 1920,
  videoHeight: 1080,
  videoFps: 24,
}

export const MAX_LYRIC_LINES_PER_PAGE = 3
export const PAGE_BREAK_SILENCE_SECONDS = 1.5
export const MAX_PAGE_DURATION_SECONDS = 15.0
export const PAGE_LEAD_SECONDS = 0.35
export const PAGE_TAIL_SECONDS = 0.35
export const PAGE_FADE_MILLISECONDS = 150

export function toCentiseconds(seconds: number): number {
  return Math.max(0, Math.round(seconds * 100))
}

export function assTimestampFromCentiseconds(centiseconds: number): string {
  const cs = Math.max(0, centiseconds)
  const hours = Math.floor(cs / 360000)
  const rem1 = cs % 360000
  const minutes = Math.floor(rem1 / 6000)
  const rem2 = rem1 % 6000
  const wholeSeconds = Math.floor(rem2 / 100)
  const fraction = rem2 % 100

  const mStr = String(minutes).padStart(2, '0')
  const sStr = String(wholeSeconds).padStart(2, '0')
  const fStr = String(fraction).padStart(2, '0')
  return `${hours}:${mStr}:${sStr}.${fStr}`
}

export function escapeAssText(value: string): string {
  return value.replace(/\\/g, '/').replace(/{/g, '(').replace(/}/g, ')').replace(/\n/g, ' ')
}

export function hexToAssColor(hex: string, alpha = 0): string {
  const cleaned = hex.replace('#', '').trim()
  if (cleaned.length !== 6) return '&H00FFFFFF'

  const r = cleaned.slice(0, 2)
  const g = cleaned.slice(2, 4)
  const b = cleaned.slice(4, 6)
  const a = Math.max(0, Math.min(255, alpha)).toString(16).padStart(2, '0').toUpperCase()

  // ASS uses &HAABBGGRR format
  return `&H${a}${b.toUpperCase()}${g.toUpperCase()}${r.toUpperCase()}`
}

export function groupPageLines(
  segments: Transcript['segments'],
  maxLines = MAX_LYRIC_LINES_PER_PAGE,
  breakSilence = PAGE_BREAK_SILENCE_SECONDS,
  maxDuration = MAX_PAGE_DURATION_SECONDS
): Transcript['segments'][] {
  const groupedLines: Transcript['segments'][] = []
  let current: Transcript['segments'] = []

  for (const segment of segments) {
    if (!segment.words || segment.words.length === 0) continue

    const gap = current.length > 0 ? segment.start - current[current.length - 1].end : 0
    const duration = current.length > 0 ? segment.end - current[0].start : 0
    const shouldBreak =
      current.length > 0 &&
      (current.length >= maxLines || gap >= breakSilence || duration > maxDuration)

    if (shouldBreak) {
      groupedLines.push(current)
      current = []
    }
    current.push(segment)
  }

  if (current.length > 0) {
    groupedLines.push(current)
  }
  return groupedLines
}

export function pageWords(page: { lines: Transcript['segments'] }): Word[] {
  return page.lines.flatMap((line) => line.words)
}

export function normalizeKaraokeTimeline(
  words: Word[],
  eventStartCs: number
): { wordStartsCs: number[]; durationsCs: number[]; karaokeEndCs: number } {
  const wordStartsCs: number[] = []

  for (const word of words) {
    const earliestStartCs = wordStartsCs.length > 0 ? wordStartsCs[wordStartsCs.length - 1] + 1 : eventStartCs
    wordStartsCs.push(Math.max(earliestStartCs, toCentiseconds(word.start)))
  }

  const lastWord = words[words.length - 1]
  const karaokeEndCs = Math.max(
    wordStartsCs[wordStartsCs.length - 1] + 1,
    toCentiseconds(lastWord.end)
  )

  const durationsCs: number[] = []
  for (let i = 0; i < wordStartsCs.length; i++) {
    const startCs = wordStartsCs[i]
    const followingStartCs = i + 1 < wordStartsCs.length ? wordStartsCs[i + 1] : karaokeEndCs
    durationsCs.push(followingStartCs - startCs)
  }

  return { wordStartsCs, durationsCs, karaokeEndCs }
}

export function buildLyricPages(
  segments: Transcript['segments'],
  options: {
    maxLines?: number
    breakSilence?: number
    maxDuration?: number
    lead?: number
    tail?: number
  } = {}
): LyricPage[] {
  const {
    maxLines = MAX_LYRIC_LINES_PER_PAGE,
    breakSilence = PAGE_BREAK_SILENCE_SECONDS,
    maxDuration = MAX_PAGE_DURATION_SECONDS,
    lead = PAGE_LEAD_SECONDS,
    tail = PAGE_TAIL_SECONDS,
  } = options

  const groupedLines = groupPageLines(segments, maxLines, breakSilence, maxDuration)
  const pages: LyricPage[] = groupedLines.map((lines) => ({
    lines,
    start: 0,
    end: 0,
    display_start_cs: 0,
    display_end_cs: 0,
    word_starts_cs: [],
    durations_cs: [],
    karaoke_end_cs: 0,
  }))

  const leadCentiseconds = toCentiseconds(lead)
  const tailCentiseconds = toCentiseconds(tail)
  let nextDisplayStartCs: number | null = null

  for (let pageIndex = 0; pageIndex < pages.length; pageIndex++) {
    const page = pages[pageIndex]
    const words = pageWords(page)
    if (words.length === 0) continue

    const sourceStartCs = toCentiseconds(words[0].start)
    const desiredDisplayStartCs = Math.max(0, sourceStartCs - leadCentiseconds)
    const displayStartCs = nextDisplayStartCs === null ? desiredDisplayStartCs : nextDisplayStartCs
    const { wordStartsCs, durationsCs, karaokeEndCs } = normalizeKaraokeTimeline(words, displayStartCs)
    const desiredDisplayEndCs = Math.max(
      karaokeEndCs,
      toCentiseconds(words[words.length - 1].end) + tailCentiseconds
    )

    page.start = words[0].start
    page.end = words[words.length - 1].end
    page.display_start_cs = displayStartCs
    page.word_starts_cs = wordStartsCs
    page.durations_cs = durationsCs
    page.karaoke_end_cs = karaokeEndCs

    if (pageIndex + 1 === pages.length) {
      page.display_end_cs = desiredDisplayEndCs
      continue
    }

    const followingWords = pageWords(pages[pageIndex + 1])
    if (followingWords.length === 0) {
      page.display_end_cs = desiredDisplayEndCs
      continue
    }

    const followingSourceStartCs = toCentiseconds(followingWords[0].start)
    const followingDesiredStartCs = Math.max(0, followingSourceStartCs - leadCentiseconds)

    if (desiredDisplayEndCs <= followingDesiredStartCs) {
      page.display_end_cs = desiredDisplayEndCs
      nextDisplayStartCs = followingDesiredStartCs
      continue
    }

    let boundaryCs: number
    if (karaokeEndCs <= followingSourceStartCs) {
      boundaryCs = Math.floor((karaokeEndCs + followingSourceStartCs) / 2)
    } else {
      boundaryCs = karaokeEndCs
    }
    page.display_end_cs = boundaryCs
    nextDisplayStartCs = boundaryCs
  }

  return pages
}

export function renderPageText(page: LyricPage): string {
  const words = pageWords(page)
  if (words.length === 0) return ''

  const karaokeParts: string[] = [`{\\fad(${PAGE_FADE_MILLISECONDS},${PAGE_FADE_MILLISECONDS})}`]
  const initialDelay = page.word_starts_cs[0] - page.display_start_cs
  if (initialDelay > 0) {
    karaokeParts.push(`{\\k${initialDelay}}`)
  }

  let wordIndex = 0
  for (let lineIndex = 0; lineIndex < page.lines.length; lineIndex++) {
    const line = page.lines[lineIndex]
    for (let lineWordIndex = 0; lineWordIndex < line.words.length; lineWordIndex++) {
      const word = line.words[lineWordIndex]
      if (lineWordIndex > 0) {
        karaokeParts.push(' ')
      }
      karaokeParts.push(`{\\kf${page.durations_cs[wordIndex]}}${escapeAssText(word.text)}`)
      wordIndex++
    }
    if (lineIndex + 1 < page.lines.length) {
      karaokeParts.push('\\N')
    }
  }

  return karaokeParts.join('')
}

export function generateAss(transcript: Transcript, style: StyleConfig): string {
  const width = style.videoWidth
  const height = style.videoHeight
  const primaryAssColor = hexToAssColor(style.primaryColor, 0)
  const secondaryAssColor = hexToAssColor(style.secondaryColor, 0)
  const outlineAssColor = hexToAssColor(style.outlineColor, 0)
  const shadowAssColor = hexToAssColor(style.shadowColor, style.shadowAlpha)

  const boldVal = style.bold ? -1 : 0
  const italicVal = style.italic ? -1 : 0

  const assLines: string[] = [
    '[Script Info]',
    'ScriptType: v4.00+',
    `PlayResX: ${width}`,
    `PlayResY: ${height}`,
    'WrapStyle: 2',
    'ScaledBorderAndShadow: yes',
    '',
    '[V4+ Styles]',
    'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, ' +
      'Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, ' +
      'MarginL, MarginR, MarginV, Encoding',
    `Style: Default,${style.fontFamily},${style.fontSize},${primaryAssColor},${secondaryAssColor},${outlineAssColor},${shadowAssColor},` +
      `${boldVal},${italicVal},0,0,100,100,0,0,1,${style.outlineWidth},${style.shadowWidth},${style.alignment},` +
      `${style.marginL},${style.marginR},${style.marginV},1`,
    '',
    '[Events]',
    'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
  ]

  const pages = buildLyricPages(transcript.segments)
  for (const page of pages) {
    const startStr = assTimestampFromCentiseconds(page.display_start_cs)
    const endStr = assTimestampFromCentiseconds(page.display_end_cs)
    const text = renderPageText(page)
    assLines.push(`Dialogue: 0,${startStr},${endStr},Default,,0,0,0,,${text}`)
  }

  return assLines.join('\n') + '\n'
}
