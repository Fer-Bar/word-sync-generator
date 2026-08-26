import type { Transcript, Word } from './types'

export function shiftWord(
  transcript: Transcript,
  segmentIndex: number,
  wordIndex: number,
  deltaSeconds: number
): Transcript {
  if (segmentIndex < 0 || segmentIndex >= transcript.segments.length) return transcript
  const segment = transcript.segments[segmentIndex]
  if (wordIndex < 0 || wordIndex >= segment.words.length) return transcript

  const newSegments = transcript.segments.map((seg, sIdx) => {
    if (sIdx !== segmentIndex) return seg

    const newWords = seg.words.map((w, wIdx) => {
      if (wIdx !== wordIndex) return w
      const newStart = Math.max(0, Math.round((w.start + deltaSeconds) * 1000) / 1000)
      const duration = w.end - w.start
      const newEnd = Math.max(newStart + 0.05, Math.round((newStart + duration) * 1000) / 1000)
      return { ...w, start: newStart, end: newEnd }
    })

    const segStart = newWords.length > 0 ? newWords[0].start : seg.start
    const segEnd = newWords.length > 0 ? newWords[newWords.length - 1].end : seg.end
    return {
      ...seg,
      start: segStart,
      end: segEnd,
      words: newWords,
    }
  })

  return { ...transcript, segments: newSegments }
}

export function shiftSegment(
  transcript: Transcript,
  segmentIndex: number,
  deltaSeconds: number
): Transcript {
  if (segmentIndex < 0 || segmentIndex >= transcript.segments.length) return transcript

  const newSegments = transcript.segments.map((seg, sIdx) => {
    if (sIdx !== segmentIndex) return seg

    const newWords = seg.words.map((w) => {
      const newStart = Math.max(0, Math.round((w.start + deltaSeconds) * 1000) / 1000)
      const duration = w.end - w.start
      const newEnd = Math.max(newStart + 0.05, Math.round((newStart + duration) * 1000) / 1000)
      return { ...w, start: newStart, end: newEnd }
    })

    const newSegStart = Math.max(0, Math.round((seg.start + deltaSeconds) * 1000) / 1000)
    const segDuration = seg.end - seg.start
    const newSegEnd = Math.max(newSegStart + 0.05, Math.round((newSegStart + segDuration) * 1000) / 1000)

    return {
      ...seg,
      start: newWords.length > 0 ? newWords[0].start : newSegStart,
      end: newWords.length > 0 ? newWords[newWords.length - 1].end : newSegEnd,
      words: newWords,
    }
  })

  return { ...transcript, segments: newSegments }
}

export function updateWord(
  transcript: Transcript,
  segmentIndex: number,
  wordIndex: number,
  updates: Partial<Pick<Word, 'text' | 'start' | 'end'>>
): Transcript {
  if (segmentIndex < 0 || segmentIndex >= transcript.segments.length) return transcript
  const segment = transcript.segments[segmentIndex]
  if (wordIndex < 0 || wordIndex >= segment.words.length) return transcript

  const newSegments = transcript.segments.map((seg, sIdx) => {
    if (sIdx !== segmentIndex) return seg

    const newWords = seg.words.map((w, wIdx) => {
      if (wIdx !== wordIndex) return w
      const text = updates.text !== undefined ? updates.text : w.text
      const start = updates.start !== undefined ? Math.max(0, Math.round(updates.start * 1000) / 1000) : w.start
      const end = updates.end !== undefined ? Math.max(start + 0.01, Math.round(updates.end * 1000) / 1000) : w.end
      return { ...w, text, start, end }
    })

    const segText = newWords.map((w) => w.text).join(' ')
    const segStart = newWords.length > 0 ? newWords[0].start : seg.start
    const segEnd = newWords.length > 0 ? newWords[newWords.length - 1].end : seg.end

    return {
      ...seg,
      text: segText,
      start: segStart,
      end: segEnd,
      words: newWords,
    }
  })

  return { ...transcript, segments: newSegments }
}

export function deleteWord(
  transcript: Transcript,
  segmentIndex: number,
  wordIndex: number
): Transcript {
  if (segmentIndex < 0 || segmentIndex >= transcript.segments.length) return transcript

  const newSegments = transcript.segments.map((seg, sIdx) => {
    if (sIdx !== segmentIndex) return seg
    const newWords = seg.words.filter((_, wIdx) => wIdx !== wordIndex)
    const segText = newWords.map((w) => w.text).join(' ')
    const segStart = newWords.length > 0 ? newWords[0].start : seg.start
    const segEnd = newWords.length > 0 ? newWords[newWords.length - 1].end : seg.end

    return {
      ...seg,
      text: segText,
      start: segStart,
      end: segEnd,
      words: newWords,
    }
  })

  return { ...transcript, segments: newSegments }
}

export function addWord(
  transcript: Transcript,
  segmentIndex: number,
  afterWordIndex: number,
  text: string
): Transcript {
  if (segmentIndex < 0 || segmentIndex >= transcript.segments.length) return transcript
  const segment = transcript.segments[segmentIndex]

  let start = 0
  let end = 0.5

  if (segment.words.length > 0) {
    if (afterWordIndex >= 0 && afterWordIndex < segment.words.length) {
      const prevWord = segment.words[afterWordIndex]
      start = prevWord.end + 0.05
      end = start + 0.4
    } else {
      const lastWord = segment.words[segment.words.length - 1]
      start = lastWord.end + 0.05
      end = start + 0.4
    }
  } else {
    start = segment.start
    end = segment.start + 0.5
  }

  const newWord: Word = {
    id: `${segment.id}-w${Date.now()}`,
    start: Math.round(start * 1000) / 1000,
    end: Math.round(end * 1000) / 1000,
    text: text.trim() || '...',
    probability: 1.0,
  }

  const newSegments = transcript.segments.map((seg, sIdx) => {
    if (sIdx !== segmentIndex) return seg
    const newWords = [...seg.words]
    const insertIdx = afterWordIndex >= 0 ? afterWordIndex + 1 : newWords.length
    newWords.splice(insertIdx, 0, newWord)

    const segText = newWords.map((w) => w.text).join(' ')
    return {
      ...seg,
      text: segText,
      start: newWords[0].start,
      end: newWords[newWords.length - 1].end,
      words: newWords,
    }
  })

  return { ...transcript, segments: newSegments }
}
