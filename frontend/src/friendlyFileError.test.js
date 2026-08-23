/**
 * Each bucket in `friendlyFileError` maps a family of raw backend exception strings to one
 * human-readable sentence. The raw string comes from:
 *
 *     log_decision(…, detail=f"{type(e).__name__}: {e}"[:200])
 *
 * Tests pin every bucket so a new error shape can be slotted into the right category without
 * accidentally breaking an existing one, and so the fallback fires for anything uncategorised
 * rather than silently dropping into the wrong bucket.
 */
import { describe, it, expect } from 'vitest'
import { friendlyFileError } from './fileErrorReason.js'

describe('friendlyFileError', () => {
  it('returns null for null/undefined/empty input', () => {
    expect(friendlyFileError(null)).toBe(null)
    expect(friendlyFileError(undefined)).toBe(null)
    expect(friendlyFileError('')).toBe(null)
  })

  it('maps 404 to file-not-found message', () => {
    expect(friendlyFileError('HttpError: <HttpError 404 when requesting …>'))
      .toMatch(/File not found/)
    expect(friendlyFileError('FileNotFoundError: no such file'))
      .toMatch(/File not found/)
  })

  it('maps 403 / forbidden / permission to permission-denied message', () => {
    expect(friendlyFileError('HttpError: <HttpError 403 Forbidden>'))
      .toMatch(/Permission denied/)
    expect(friendlyFileError('PermissionError: access denied to resource'))
      .toMatch(/Permission denied/)
    expect(friendlyFileError('Error: forbidden by policy'))
      .toMatch(/Permission denied/)
  })

  it('maps 401 / unauthorized to authentication-expired message', () => {
    expect(friendlyFileError('HttpError: <HttpError 401 Unauthorized>'))
      .toMatch(/Authentication expired/)
    expect(friendlyFileError('AuthError: unauthorized'))
      .toMatch(/Authentication expired/)
  })

  it('maps 429 / rate limit / quota to rate-limited message', () => {
    expect(friendlyFileError('HttpError: <HttpError 429 Too Many Requests>'))
      .toMatch(/Rate limited/)
    expect(friendlyFileError('RateLimitError: rate limit exceeded'))
      .toMatch(/Rate limited/)
    expect(friendlyFileError('QuotaExceededError: daily quota exceeded'))
      .toMatch(/Rate limited/)
  })

  it('maps timeout shapes to timed-out message', () => {
    expect(friendlyFileError('ReadTimeout: timed out after 30s'))
      .toMatch(/timed out/i)
    expect(friendlyFileError('TimeoutException: request timeout'))
      .toMatch(/timed out/i)
  })

  it('maps password / encrypted to password-protected message', () => {
    expect(friendlyFileError('EncryptedDocumentError: file is password-protected'))
      .toMatch(/password-protected/)
    expect(friendlyFileError('ValueError: encrypted file cannot be opened'))
      .toMatch(/password-protected/)
  })

  it('maps corrupt / invalid / parse to corrupted-or-unsupported message', () => {
    // Real Python exceptions from docx/pdf/xlsx parsers:
    expect(friendlyFileError('XMLSyntaxError: failed to parse XML content'))
      .toMatch(/corrupted/)
    expect(friendlyFileError('InvalidFormatError: cannot open document'))
      .toMatch(/corrupted/)
    expect(friendlyFileError('ParseError: unexpected token in XML'))
      .toMatch(/corrupted/)
    expect(friendlyFileError('CorruptionError: document structure is corrupt'))
      .toMatch(/corrupted/)
  })

  it('maps size / too large to size-exceeded message', () => {
    expect(friendlyFileError('FileTooLargeError: file size exceeds limit'))
      .toMatch(/maximum supported size/)
    expect(friendlyFileError('ValueError: too large to process'))
      .toMatch(/maximum supported size/)
  })

  it('maps unsupported / mime / type to unsupported-file-type message', () => {
    expect(friendlyFileError('UnsupportedMimeType: application/x-unknown'))
      .toMatch(/not supported/)
    expect(friendlyFileError('TypeError: unsupported file format'))
      .toMatch(/not supported/)
  })

  it('falls back to generic skip message for unrecognised errors', () => {
    expect(friendlyFileError('AttributeError: object has no attribute "files"'))
      .toMatch(/Could not open this file/)
    expect(friendlyFileError('SomeOtherException: something went wrong'))
      .toMatch(/Could not open this file/)
  })

  it('matches case-insensitively — error strings from Python can be CamelCase or UPPER', () => {
    expect(friendlyFileError('HTTPERROR: 403')).toMatch(/Permission denied/)
    expect(friendlyFileError('TIMEOUT: connection timed out')).toMatch(/timed out/i)
  })

  it('coerces non-string input to string before matching', () => {
    // The backend detail field is always a string, but defensive against unexpected shapes.
    expect(friendlyFileError(404)).toMatch(/File not found/)
    expect(friendlyFileError({ toString: () => 'timeout occurred' })).toMatch(/timed out/i)
  })
})
