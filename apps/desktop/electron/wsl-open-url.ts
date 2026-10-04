/**
 * Build an argv that opens `url` in the Windows default browser from a WSL
 * desktop session without a shell re-parse.
 *
 * cmd.exe re-parses its command line (`&`, `|`, `^`, `%VAR%` are operators and
 * expansions), and neither Node's argv quoting nor the WSL interop layer adds
 * cmd-level quoting for space-free arguments, so routing a URL through
 * `cmd /c start "" <url>` lets URL bytes act as a second command. rundll32 with
 * url.dll,FileProtocolHandler receives the URL as a plain CreateProcess
 * argument, which URL characters (`& ? # = %` …) survive unchanged. A URL
 * containing characters that cannot round-trip CreateProcess argument quoting
 * is rejected rather than opened.
 */
export function wslOpenUrlArgv(url: string): string[] | null {
  // Quotes and control characters cannot survive CreateProcess argument
  // quoting; everything else a URL can legally contain is a literal argument.
  // eslint-disable-next-line no-control-regex -- rejecting control characters IS the check
  if (/["\u0000-\u001f\u007f]/.test(url)) {
    return null
  }
  // Only the schemes the opener allowlists upstream; anything else is not ours
  // to hand to the host shell.
  if (!/^(https?|mailto):/i.test(url)) {
    return null
  }
  return ['rundll32.exe', 'url.dll,FileProtocolHandler', url]
}
