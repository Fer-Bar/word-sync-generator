export function formatTimestamp(seconds: number): string {
  const milliseconds = Math.max(0, Math.round((Number.isFinite(seconds) ? seconds : 0) * 1000))
  const minutes = Math.floor(milliseconds / 60_000)
  const remaining = milliseconds % 60_000
  const wholeSeconds = Math.floor(remaining / 1000)
  const fraction = remaining % 1000

  return `${String(minutes).padStart(2, '0')}:${String(wholeSeconds).padStart(2, '0')}.${String(fraction).padStart(3, '0')}`
}

export function parseTimestamp(value: string): number | null {
  const input = value.trim().replace(',', '.')
  if (!input) return null

  const parts = input.split(':')
  if (parts.length > 3 || parts.some((part) => !/^\d+(?:\.\d+)?$/.test(part))) return null

  const numbers = parts.map(Number)
  if (numbers.some((part) => !Number.isFinite(part) || part < 0)) return null

  let seconds: number
  if (numbers.length === 1) {
    seconds = numbers[0]
  } else if (numbers.length === 2) {
    if (numbers[1] >= 60) return null
    seconds = numbers[0] * 60 + numbers[1]
  } else {
    if (numbers[1] >= 60 || numbers[2] >= 60) return null
    seconds = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
  }

  return Math.round(seconds * 1000) / 1000
}
