import { describe, expect, it } from 'vitest'

import { wslOpenUrlArgv } from './wsl-open-url'

/**
 * CreateProcess-style argument quoting round-trip, per the documented Windows
 * rules: an argument is quoted iff it contains whitespace or a quote; 2n
 * backslashes before a quote become n backslashes plus the quote; trailing
 * backslashes before the closing quote are doubled. A URL that comes back
 * byte-identical can never leak operators into a downstream parser.
 */
function quoteWindowsArg(arg: string): string {
  if (!/[\s"]/.test(arg)) {
    return arg
  }
  let out = '"'
  let backslashes = 0
  for (const ch of arg) {
    if (ch === '\\') {
      backslashes += 1
      continue
    }
    if (ch === '"') {
      out += '\\'.repeat(backslashes * 2 + 1) + '"'
    } else {
      out += '\\'.repeat(backslashes) + ch
    }
    backslashes = 0
  }
  out += '\\'.repeat(backslashes * 2) + '"'
  return out
}

/** Split a CreateProcess-style command line back into arguments. */
function parseWindowsArgs(cmdline: string): string[] {
  const args: string[] = []
  let cur = ''
  let quoted = false
  let hasToken = false
  let backslashes = 0
  for (let i = 0; i < cmdline.length; i += 1) {
    const ch = cmdline[i]
    if (ch === '\\') {
      backslashes += 1
      continue
    }
    if (ch === '"') {
      if (backslashes % 2 === 0) {
        if (quoted && cmdline[i + 1] === '"') {
          cur += '"'
          i += 1
        } else {
          quoted = !quoted
        }
      } else {
        cur += '\\'.repeat(Math.floor(backslashes / 2)) + '"'
      }
      hasToken = true
    } else if ((ch === ' ' || ch === '\t') && !quoted) {
      // Unquoted whitespace delimits arguments (CommandLineToArgvW rule).
      if (hasToken) {
        args.push(cur)
        cur = ''
        hasToken = false
      }
    } else {
      cur += '\\'.repeat(backslashes) + ch
      hasToken = true
    }
    backslashes = 0
  }
  if (backslashes) {
    cur += '\\'.repeat(backslashes)
    hasToken = true
  }
  if (hasToken || quoted) {
    args.push(cur)
  }
  return args
}

describe('wslOpenUrlArgv', () => {
  it('never routes URLs through a shell that re-parses the command line', () => {
    const argv = wslOpenUrlArgv('https://example.com/a?b=1&c=2')
    expect(argv).not.toBeNull()
    expect(argv?.[0].toLowerCase()).not.toContain('cmd')
    expect(argv?.[0].toLowerCase()).toBe('rundll32.exe')
  })

  it('keeps cmd.exe metacharacters in the URL as literal argument bytes', () => {
    const hostile = 'https://evil.example/?a=1&calc.exe^whoami%PATH%'
    const argv = wslOpenUrlArgv(hostile)
    expect(argv).not.toBeNull()
    expect(argv?.[2]).toBe(hostile)
  })

  it('round-trips every allowlisted URL byte-identically through CreateProcess quoting', () => {
    const urls = [
      'https://example.com/path with spaces/q?a=1&b=2#frag',
      'http://example.com/%41%42?a=1&c=^|%PATH%',
      'mailto:someone@example.com?subject=hi%20there&body=a&b',
    ]
    for (const url of urls) {
      const argv = wslOpenUrlArgv(url)
      expect(argv).not.toBeNull()
      const cmdline = argv.map(quoteWindowsArg).join(' ')
      expect(parseWindowsArgs(cmdline)).toEqual(argv)
    }
  })

  it('rejects URLs containing characters that cannot survive argv quoting', () => {
    expect(wslOpenUrlArgv('https://example.com/a"&calc.exe')).toBeNull()
    expect(wslOpenUrlArgv('https://example.com/a\u0000b')).toBeNull()
    expect(wslOpenUrlArgv('https://example.com/a\u001fb')).toBeNull()
    expect(wslOpenUrlArgv('https://example.com/a\u007fb')).toBeNull()
  })

  it('accepts exactly the schemes the opener allowlists upstream', () => {
    expect(wslOpenUrlArgv('https://example.com')).not.toBeNull()
    expect(wslOpenUrlArgv('http://example.com')).not.toBeNull()
    expect(wslOpenUrlArgv('mailto:someone@example.com')).not.toBeNull()
    expect(wslOpenUrlArgv('ftp://example.com')).toBeNull()
    expect(wslOpenUrlArgv('javascript:alert(1)')).toBeNull()
    expect(wslOpenUrlArgv('file:///etc/passwd')).toBeNull()
  })
})
