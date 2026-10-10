import test from 'node:test'
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
import { join } from 'node:path'

const buildDir = process.env.METRICSLEUTH_DECIMAL_BUILD_DIR
if (!buildDir) throw new Error('METRICSLEUTH_DECIMAL_BUILD_DIR is required')
const { formatDecimal } = await import(pathToFileURL(join(buildDir, 'product/formatDecimal.js')).href)

test('rounds long fractional values to four places and marks only nonzero discarded digits', () => {
  assert.deepEqual(formatDecimal('12.345678901234567890'), {
    display: '12.3457', raw: '12.345678901234567890', approximate: true,
  })
  assert.deepEqual(formatDecimal('12.34000'), {
    display: '12.34', raw: '12.34000', approximate: false,
  })
})

test('preserves large integer precision and groups thousands', () => {
  assert.deepEqual(formatDecimal('9007199254740993'), {
    display: '9,007,199,254,740,993', raw: '9007199254740993', approximate: false,
  })
})

test('rounds negative values half away from zero and carries into the integer part', () => {
  assert.equal(formatDecimal('-1.23445').display, '-1.2345')
  assert.equal(formatDecimal('-1.23445').approximate, true)
  assert.equal(formatDecimal('999.99999').display, '1,000')
})

test('normalizes negative zero for display while preserving a string raw value', () => {
  assert.deepEqual(formatDecimal('-0.000000'), {
    display: '0', raw: '-0.000000', approximate: false,
  })
  assert.deepEqual(formatDecimal(-0), { display: '0', raw: '0', approximate: false })
})

test('keeps null distinct from zero', () => {
  assert.deepEqual(formatDecimal(null), { display: '—', raw: null, approximate: false })
})

test('supports bounded scientific notation without losing decimal digits', () => {
  assert.deepEqual(formatDecimal('1.23456e3'), {
    display: '1,234.56', raw: '1.23456e3', approximate: false,
  })
  assert.deepEqual(formatDecimal('5e-5'), {
    display: '0.0001', raw: '5e-5', approximate: true,
  })
  assert.deepEqual(formatDecimal('1.2e-3'), {
    display: '0.0012', raw: '1.2e-3', approximate: false,
  })
})

test('handles rounding carry, exact ties and removable trailing zeros', () => {
  assert.equal(formatDecimal('0.00005').display, '0.0001')
  assert.equal(formatDecimal('1.99995').display, '2')
  assert.equal(formatDecimal('1.230000').display, '1.23')
  assert.equal(formatDecimal('1.230000').approximate, false)
})

test('falls back to the original representation for extreme or malformed inputs', () => {
  for (const raw of ['1e999999', '1e-999999', 'not-a-decimal']) {
    assert.deepEqual(formatDecimal(raw), { display: raw, raw, approximate: false })
  }
})

test('does not mutate string inputs', () => {
  const input = '00012345678901234567890.123456789'
  const before = input.slice()
  formatDecimal(input)
  assert.equal(input, before)
})

test('uses only the provided JavaScript number string representation', () => {
  const value = Number.MAX_SAFE_INTEGER + 2
  assert.deepEqual(formatDecimal(value), {
    display: '9,007,199,254,740,992', raw: String(value), approximate: false,
  })
})
