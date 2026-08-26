import type { Segment, Transcript, ValidationError, Word } from './types'

export function parseTranscript(jsonString: string): Transcript {
  const data = JSON.parse(jsonString)
  if (!data || typeof data !== 'object') {
    throw new Error('Invalid JSON format for transcript')
  }

  if (typeof data.schema_version !== 'number') {
    throw new Error("Missing or invalid 'schema_version'")
  }

  if (!data.song || typeof data.song !== 'object' || !data.song.title) {
    throw new Error("Missing required 'song.title' metadata")
  }

  if (!Array.isArray(data.segments)) {
    throw new Error("Missing or invalid 'segments' array")
  }

  // Normalize segments and words
  const normalizedSegments: Segment[] = data.segments.map((seg: any, segIdx: number) => {
    const segId = typeof seg.id === 'string' && seg.id ? seg.id : `s${segIdx}`
    const rawWords: any[] = Array.isArray(seg.words) ? seg.words : []

    const words: Word[] = rawWords.map((w: any, wordIdx: number) => {
      const wordId = typeof w.id === 'string' && w.id ? w.id : `${segId}-w${wordIdx}`
      const start = Number(w.start) || 0
      const end = Number(w.end) || start + 0.1
      const text = typeof w.text === 'string' ? w.text : ''
      return {
        id: wordId,
        start: Math.round(start * 1000) / 1000,
        end: Math.round(end * 1000) / 1000,
        text,
        probability: typeof w.probability === 'number' ? w.probability : 1.0,
      }
    })

    const segStart = typeof seg.start === 'number' ? seg.start : (words[0]?.start ?? 0)
    const segEnd = typeof seg.end === 'number' ? seg.end : (words[words.length - 1]?.end ?? segStart + 0.5)
    const segText = typeof seg.text === 'string' && seg.text ? seg.text : words.map((w) => w.text).join(' ')

    return {
      id: segId,
      start: Math.round(segStart * 1000) / 1000,
      end: Math.round(segEnd * 1000) / 1000,
      text: segText,
      words,
    }
  })

  return {
    schema_version: data.schema_version,
    song: {
      title: String(data.song.title),
      uploader: data.song.uploader ?? null,
      duration: typeof data.song.duration === 'number' ? data.song.duration : null,
    },
    transcription: data.transcription,
    segments: normalizedSegments,
  }
}

export function validateTranscript(transcript: Transcript): ValidationError[] {
  const errors: ValidationError[] = []

  if (!transcript.song?.title?.trim()) {
    errors.push({
      type: 'error',
      message: 'Song title is required',
      field: 'song.title',
    })
  }

  if (transcript.segments.length === 0) {
    errors.push({
      type: 'error',
      message: 'Transcript must have at least one segment',
      field: 'segments',
    })
    return errors
  }

  const seenWordIds = new Set<string>()
  const seenSegmentIds = new Set<string>()

  transcript.segments.forEach((segment, segIdx) => {
    if (seenSegmentIds.has(segment.id)) {
      errors.push({
        type: 'error',
        message: `Duplicate segment ID: ${segment.id}`,
        segmentIndex: segIdx,
        field: 'segment.id',
      })
    }
    seenSegmentIds.add(segment.id)

    if (segment.start < 0 || !Number.isFinite(segment.start)) {
      errors.push({
        type: 'error',
        message: `Segment ${segIdx + 1} start time is invalid (${segment.start}s)`,
        segmentIndex: segIdx,
        field: 'segment.start',
      })
    }

    if (segment.end <= segment.start || !Number.isFinite(segment.end)) {
      errors.push({
        type: 'error',
        message: `Segment ${segIdx + 1} end time (${segment.end}s) must be greater than start (${segment.start}s)`,
        segmentIndex: segIdx,
        field: 'segment.end',
      })
    }

    if (segment.words.length === 0) {
      errors.push({
        type: 'warning',
        message: `Segment ${segIdx + 1} contains no words`,
        segmentIndex: segIdx,
        field: 'segment.words',
      })
    }

    let prevWordEnd = 0
    segment.words.forEach((word, wordIdx) => {
      if (seenWordIds.has(word.id)) {
        errors.push({
          type: 'error',
          message: `Duplicate word ID: ${word.id}`,
          segmentIndex: segIdx,
          wordIndex: wordIdx,
          field: 'word.id',
        })
      }
      seenWordIds.add(word.id)

      if (!word.text.trim()) {
        errors.push({
          type: 'warning',
          message: `Word ${wordIdx + 1} in segment ${segIdx + 1} is empty`,
          segmentIndex: segIdx,
          wordIndex: wordIdx,
          field: 'word.text',
        })
      }

      if (word.start < 0 || !Number.isFinite(word.start)) {
        errors.push({
          type: 'error',
          message: `Word "${word.text}" start time is invalid (${word.start}s)`,
          segmentIndex: segIdx,
          wordIndex: wordIdx,
          field: 'word.start',
        })
      }

      if (word.end <= word.start || !Number.isFinite(word.end)) {
        errors.push({
          type: 'error',
          message: `Word "${word.text}" end (${word.end}s) must be greater than start (${word.start}s)`,
          segmentIndex: segIdx,
          wordIndex: wordIdx,
          field: 'word.end',
        })
      }

      if (wordIdx > 0 && word.start < prevWordEnd - 0.05) {
        errors.push({
          type: 'warning',
          message: `Word "${word.text}" starts (${word.start}s) before previous word ends (${prevWordEnd}s)`,
          segmentIndex: segIdx,
          wordIndex: wordIdx,
          field: 'word.start',
        })
      }
      prevWordEnd = word.end
    })
  })

  return errors
}
