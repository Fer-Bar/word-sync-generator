import type { Segment, TimingFragment, Transcript, Word } from './types'

const round = (value: number) => Math.round(value * 1000) / 1000

function rebuildSegment(segment: Segment, words: Word[]): Segment {
  return {
    ...segment,
    words,
    text: words.map((word) => word.text).join(' '),
    start: Math.min(...words.map((word) => word.start)),
    end: Math.max(...words.map((word) => word.end)),
  }
}

function selectedWord(transcript: Transcript, segmentIndex: number, wordIndex: number): Word | null {
  return transcript.segments[segmentIndex]?.words[wordIndex] ?? null
}

function replaceWord(
  transcript: Transcript,
  segmentIndex: number,
  wordIndex: number,
  replacement: Word,
): Transcript {
  const current = selectedWord(transcript, segmentIndex, wordIndex)
  if (!current || current === replacement) return transcript
  const segments = transcript.segments.map((segment, index) =>
    index === segmentIndex
      ? rebuildSegment(segment, segment.words.map((word, position) => (position === wordIndex ? replacement : word)))
      : segment,
  )
  return { ...transcript, schema_version: 2, segments }
}

function retimeFragments(word: Word, start: number, end: number): TimingFragment[] | undefined {
  if (!word.timing || end <= start) return undefined
  const sourceDuration = word.end - word.start
  if (sourceDuration <= 0) return undefined
  return word.timing.map((fragment, index) => ({
    ...fragment,
    start: index === 0 ? start : round(start + ((fragment.start - word.start) / sourceDuration) * (end - start)),
    end:
      index === word.timing!.length - 1
        ? end
        : round(start + ((fragment.end - word.start) / sourceDuration) * (end - start)),
  }))
}

export function updateWord(
  transcript: Transcript,
  segmentIndex: number,
  wordIndex: number,
  updates: Partial<Pick<Word, 'text' | 'start' | 'end'>>,
): Transcript {
  const word = selectedWord(transcript, segmentIndex, wordIndex)
  if (!word) return transcript
  const text = updates.text?.trim() ?? word.text
  if (!text) return transcript
  const start = updates.start === undefined ? word.start : round(Math.max(0, updates.start))
  const end = updates.end === undefined ? word.end : round(updates.end)
  const textChanged = text !== word.text
  if (text === word.text && start === word.start && end === word.end) return transcript
  if (end <= start) return transcript
  const timing = textChanged ? undefined : retimeFragments(word, start, end)
  return replaceWord(transcript, segmentIndex, wordIndex, {
    ...word,
    text,
    start,
    end,
    ...(timing ? { timing } : {}),
    ...(!timing ? { timing: undefined } : {}),
  })
}

export function nudgeWordBoundary(
  transcript: Transcript,
  segmentIndex: number,
  wordIndex: number,
  boundary: 'start' | 'end',
  delta: number,
): Transcript {
  const word = selectedWord(transcript, segmentIndex, wordIndex)
  return word ? updateWord(transcript, segmentIndex, wordIndex, { [boundary]: word[boundary] + delta }) : transcript
}

export function deleteWord(transcript: Transcript, segmentIndex: number, wordIndex: number): Transcript {
  if (transcript.segments.reduce((count, segment) => count + segment.words.length, 0) <= 1) return transcript
  const segment = transcript.segments[segmentIndex]
  if (!segment?.words[wordIndex]) return transcript
  const words = segment.words.filter((_, index) => index !== wordIndex)
  const segments = words.length
    ? transcript.segments.map((item, index) => (index === segmentIndex ? rebuildSegment(item, words) : item))
    : transcript.segments.filter((_, index) => index !== segmentIndex)
  return { ...transcript, schema_version: 2, segments }
}

function uniqueSegmentId(transcript: Transcript, base: string): string {
  const ids = new Set(transcript.segments.map((segment) => segment.id))
  let index = 1
  while (ids.has(`${base}-${index}`)) index += 1
  return `${base}-${index}`
}

export function splitLineBefore(transcript: Transcript, segmentIndex: number, wordIndex: number): Transcript {
  const segment = transcript.segments[segmentIndex]
  if (!segment || wordIndex <= 0 || wordIndex >= segment.words.length) return transcript
  const first = rebuildSegment(segment, segment.words.slice(0, wordIndex))
  const second = rebuildSegment(
    { ...segment, id: uniqueSegmentId(transcript, `${segment.id}-split`) },
    segment.words.slice(wordIndex),
  )
  const segments = [...transcript.segments]
  segments.splice(segmentIndex, 1, first, second)
  return { ...transcript, schema_version: 2, segments }
}

export function moveWordToNextLine(transcript: Transcript, segmentIndex: number, wordIndex: number): Transcript {
  const segment = transcript.segments[segmentIndex]
  const word = segment?.words[wordIndex]
  if (!segment || !word) return transcript
  const remaining = segment.words.filter((_, index) => index !== wordIndex)
  const following = transcript.segments[segmentIndex + 1]
  const target = following
    ? rebuildSegment(following, [word, ...following.words])
    : rebuildSegment({ ...segment, id: uniqueSegmentId(transcript, `${segment.id}-next`) }, [word])
  const segments = [...transcript.segments]
  if (remaining.length) {
    segments[segmentIndex] = rebuildSegment(segment, remaining)
    if (following) segments[segmentIndex + 1] = target
    else segments.push(target)
  } else {
    segments.splice(segmentIndex, following ? 2 : 1, target)
  }
  return { ...transcript, schema_version: 2, segments }
}

export function mergeLineWithNext(transcript: Transcript, segmentIndex: number): Transcript {
  const current = transcript.segments[segmentIndex]
  const following = transcript.segments[segmentIndex + 1]
  if (!current || !following) return transcript
  const segments = [...transcript.segments]
  segments.splice(segmentIndex, 2, rebuildSegment(current, [...current.words, ...following.words]))
  return { ...transcript, schema_version: 2, segments }
}

export function normalizeLineGaps(transcript: Transcript, segmentIndex: number): Transcript {
  const segment = transcript.segments[segmentIndex]
  if (!segment || segment.words.length < 2) return transcript
  const words = segment.words.map((word, index) => {
    if (index === segment.words.length - 1) return word
    const end = segment.words[index + 1].start
    if (end <= word.start) return word
    const timing = retimeFragments(word, word.start, end)
    return { ...word, end, ...(timing ? { timing } : { timing: undefined }) }
  })
  if (words.every((word, index) => word.end === segment.words[index].end)) return transcript
  const segments = transcript.segments.map((item, index) => (index === segmentIndex ? rebuildSegment(item, words) : item))
  return { ...transcript, schema_version: 2, segments }
}

export function setWordTimingPattern(
  transcript: Transcript,
  segmentIndex: number,
  wordIndex: number,
  pattern: string,
): Transcript {
  const word = selectedWord(transcript, segmentIndex, wordIndex)
  const parts = pattern.split('|')
  if (!word || parts.length < 2 || parts.some((part) => !part) || parts.join('') !== word.text || word.end <= word.start) {
    return transcript
  }
  const totalUnits = parts.reduce((total, part) => total + Array.from(part).length, 0)
  let cursor = word.start
  const timing = parts.map((text, index) => {
    const start = cursor
    cursor = index === parts.length - 1 ? word.end : round(cursor + ((word.end - word.start) * Array.from(text).length) / totalUnits)
    return { id: `${word.id}-f${index}`, text, start, end: cursor }
  })
  return replaceWord(transcript, segmentIndex, wordIndex, { ...word, timing })
}

export function setFragmentBoundary(
  transcript: Transcript,
  segmentIndex: number,
  wordIndex: number,
  boundaryIndex: number,
  value: number,
): Transcript {
  const word = selectedWord(transcript, segmentIndex, wordIndex)
  if (!word?.timing || boundaryIndex < 0 || boundaryIndex >= word.timing.length - 1) return transcript
  const minimum = word.timing[boundaryIndex].start + 0.001
  const maximum = word.timing[boundaryIndex + 1].end - 0.001
  const boundary = round(Math.min(maximum, Math.max(minimum, value)))
  if (boundary === word.timing[boundaryIndex].end) return transcript
  const timing = word.timing.map((fragment, index) => {
    if (index === boundaryIndex) return { ...fragment, end: boundary }
    if (index === boundaryIndex + 1) return { ...fragment, start: boundary }
    return fragment
  })
  return replaceWord(transcript, segmentIndex, wordIndex, { ...word, timing })
}
