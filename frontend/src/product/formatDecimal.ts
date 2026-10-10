import type { DecimalValue } from '../tasks/contracts'

export interface FormattedDecimal {
  display: string
  raw: string | null
  approximate: boolean
}

const MAX_RAW_LENGTH = 4096
const MAX_EXPANSION = 4096
const DECIMAL_PATTERN = /^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))(?:[eE]([+-]?\d+))?$/

function addOne(value: string): string {
  const digits = value.split('')
  for (let index = digits.length - 1; index >= 0; index -= 1) {
    if (digits[index] !== '9') {
      digits[index] = String.fromCharCode(digits[index].charCodeAt(0) + 1)
      return digits.join('')
    }
    digits[index] = '0'
  }
  return `1${digits.join('')}`
}

function groupInteger(value: string): string {
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

function fallback(raw: string): FormattedDecimal {
  return { display: raw, raw, approximate: false }
}

/** Formats a decimal for compact display without passing its value through Number. */
export function formatDecimal(value: DecimalValue | null): FormattedDecimal {
  if (value === null) return { display: '—', raw: null, approximate: false }

  // For number inputs, this is only the representation JavaScript already received.
  const raw = typeof value === 'number' ? String(value) : value
  if (raw.length > MAX_RAW_LENGTH) return fallback(raw)

  const match = DECIMAL_PATTERN.exec(raw)
  if (!match) return fallback(raw)

  const sign = match[1] === '-' ? '-' : ''
  const integerPart = match[2] ?? '0'
  const fractionPart = match[3] ?? match[4] ?? ''
  const exponentText = match[5] ?? '0'
  // Avoid parsing an unbounded exponent string or expanding a hostile value.
  if (exponentText.length > 5) return fallback(raw)
  const exponent = Number(exponentText)
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > MAX_EXPANSION) return fallback(raw)

  const digits = `${integerPart}${fractionPart}`.replace(/^0+/, '') || '0'
  const scale = fractionPart.length - exponent
  let scaled: string
  let approximate = false

  if (scale <= 4) {
    const zeroCount = 4 - scale
    if (digits.length + zeroCount > MAX_EXPANSION) return fallback(raw)
    scaled = `${digits}${'0'.repeat(zeroCount)}`
  } else {
    const discardedCount = scale - 4
    const keptCount = digits.length - discardedCount
    const kept = keptCount > 0 ? digits.slice(0, keptCount) : '0'
    const firstDiscarded = keptCount >= 0 ? digits[keptCount] : '0'
    const discarded = keptCount >= 0 ? digits.slice(keptCount) : digits
    approximate = /[1-9]/.test(discarded)
    scaled = firstDiscarded >= '5' ? addOne(kept) : kept
  }

  if (scaled.length > MAX_EXPANSION) return fallback(raw)
  const padded = scaled.padStart(5, '0')
  const integer = padded.slice(0, -4).replace(/^0+(?=\d)/, '')
  const fraction = padded.slice(-4).replace(/0+$/, '')
  const magnitude = fraction ? `${groupInteger(integer)}.${fraction}` : groupInteger(integer)
  const isZero = /^0(?:\.0*)?$/.test(magnitude)
  return {
    display: sign && !isZero ? `-${magnitude}` : magnitude,
    raw,
    approximate,
  }
}
