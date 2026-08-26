import { describe, expect, it } from 'vitest'
import {
  assTimestampFromCentiseconds,
  buildLyricPages,
  DEFAULT_STYLE_CONFIG,
  generateAss,
  hexToAssColor,
} from '../assGenerator'
import { shiftSegment, shiftWord, updateWord } from '../timing'
import { parseTranscript, validateTranscript } from '../transcript'
import type { Transcript } from '../types'

const sampleJson = JSON.stringify({
  schema_version: 1,
  song: {
    title: 'Test Song',
    uploader: 'Artist',
    duration: 120.5,
  },
  segments: [
    {
      id: 's0',
      start: 1.0,
      end: 3.5,
      text: 'Hello world today',
      words: [
        { id: 's0-w0', start: 1.0, end: 1.8, text: 'Hello' },
        { id: 's0-w1', start: 1.9, end: 2.5, text: 'world' },
        { id: 's0-w2', start: 2.6, end: 3.5, text: 'today' },
      ],
    },
    {
      id: 's1',
      start: 6.0,
      end: 8.0,
      text: 'Sing along now',
      words: [
        { id: 's1-w0', start: 6.0, end: 6.8, text: 'Sing' },
        { id: 's1-w1', start: 6.9, end: 7.4, text: 'along' },
        { id: 's1-w2', start: 7.5, end: 8.0, text: 'now' },
      ],
    },
  ],
})

describe('Transcript Domain', () => {
  it('parses and normalizes transcript json correctly', () => {
    const parsed = parseTranscript(sampleJson)
    expect(parsed.schema_version).toBe(1)
    expect(parsed.song.title).toBe('Test Song')
    expect(parsed.segments.length).toBe(2)
    expect(parsed.segments[0].words.length).toBe(3)
  })

  it('validates a valid transcript without errors', () => {
    const parsed = parseTranscript(sampleJson)
    const errors = validateTranscript(parsed)
    expect(errors.filter((e) => e.type === 'error').length).toBe(0)
  })

  it('detects invalid timing ranges and empty titles', () => {
    const invalid: Transcript = {
      schema_version: 1,
      song: { title: '' },
      segments: [
        {
          id: 's0',
          start: 5.0,
          end: 3.0, // end < start!
          text: 'bad segment',
          words: [],
        },
      ],
    }
    const errors = validateTranscript(invalid)
    expect(errors.some((e) => e.field === 'song.title')).toBe(true)
    expect(errors.some((e) => e.field === 'segment.end')).toBe(true)
  })

  it('shifts a single word correctly', () => {
    const parsed = parseTranscript(sampleJson)
    const shifted = shiftWord(parsed, 0, 1, 0.2) // shift "world" +200ms
    expect(shifted.segments[0].words[1].start).toBe(2.1)
    expect(shifted.segments[0].words[1].end).toBe(2.7)
  })

  it('shifts an entire segment and its words correctly', () => {
    const parsed = parseTranscript(sampleJson)
    const shifted = shiftSegment(parsed, 0, 0.5) // shift +500ms
    expect(shifted.segments[0].start).toBe(1.5)
    expect(shifted.segments[0].words[0].start).toBe(1.5)
    expect(shifted.segments[0].words[1].start).toBe(2.4)
  })

  it('updates word text and updates segment text', () => {
    const parsed = parseTranscript(sampleJson)
    const updated = updateWord(parsed, 0, 0, { text: 'Goodbye' })
    expect(updated.segments[0].words[0].text).toBe('Goodbye')
    expect(updated.segments[0].text).toBe('Goodbye world today')
  })
})

describe('ASS Generator Domain', () => {
  it('converts centiseconds to ASS timestamps properly', () => {
    expect(assTimestampFromCentiseconds(0)).toBe('0:00:00.00')
    expect(assTimestampFromCentiseconds(125)).toBe('0:00:01.25')
    expect(assTimestampFromCentiseconds(6540)).toBe('0:01:05.40')
    expect(assTimestampFromCentiseconds(366120)).toBe('1:01:01.20')
  })

  it('converts RGB hex to ASS &HAABBGGRR format', () => {
    expect(hexToAssColor('#00D7FF', 0)).toBe('&H00FFD700')
    expect(hexToAssColor('#FFFFFF', 0)).toBe('&H00FFFFFF')
    expect(hexToAssColor('#000000', 112)).toBe('&H70000000')
  })

  it('builds lyric pages splitting on silence >= 1.5s', () => {
    const parsed = parseTranscript(sampleJson)
    const pages = buildLyricPages(parsed.segments)
    expect(pages.length).toBe(2)
    expect(pages[0].lines.length).toBe(1)
    expect(pages[1].lines.length).toBe(1)
  })

  it('generates complete ASS subtitle string with styles and events', () => {
    const parsed = parseTranscript(sampleJson)
    const ass = generateAss(parsed, DEFAULT_STYLE_CONFIG)
    expect(ass).toContain('[Script Info]')
    expect(ass).toContain('[V4+ Styles]')
    expect(ass).toContain('Style: Default,DejaVu Sans,64')
    expect(ass).toContain('[Events]')
    expect(ass).toContain('Dialogue: 0,')
    expect(ass).toContain('{\\kf')
    expect(ass).toContain('Hello')
  })
})
