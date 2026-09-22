/** Shared bridge between the dsh tools and the `macos-cu` CLI. @module macosCu */

import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

export const MISSING_BINARY_MESSAGE =
  'macos-cu was not found (checked MACOS_CU_BIN, ~/.local/bin, ' +
  '~/.local/share/macos-computer-use/venv/bin, and PATH). Install it with ' +
  '`pip install macos-computer-use-kit` (or `pipx install macos-computer-use-kit`) on ' +
  'macOS — https://github.com/Sur-Cai/macos-computer-use-kit — then retry. If it lives ' +
  'somewhere unusual, set MACOS_CU_BIN to the absolute path. On macOS, grant the host ' +
  'process Accessibility and Screen Recording permissions (`macos-cu doctor` reports both).'

/**
 * Resolve the CLI: explicit override, then a well-known install location, then
 * PATH. GUI-launched agents do not inherit an interactive shell's PATH, so the
 * known locations (pip/pipx and this repo's install.sh) are checked directly.
 */
export function binary(): string {
  const override = process.env['MACOS_CU_BIN']?.trim()
  if (override !== undefined && override.length > 0) return override
  const candidates = [
    join(homedir(), '.local', 'bin', 'macos-cu'),
    join(homedir(), '.local', 'share', 'macos-computer-use', 'venv', 'bin', 'macos-cu'),
  ]
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate
  }
  return 'macos-cu'
}

/**
 * Run the CLI with an argument array (never a shell string) and return the
 * outcome. Missing-binary (ENOENT) resolves to an actionable install message
 * instead of throwing, so the model sees what to do next.
 */
export async function runMacosCu(argv: string[], signal: AbortSignal): Promise<string> {
  if (signal.aborted) throw new Error('macos-cu call aborted before spawn')
  const bin = binary()
  const outcome = await new Promise<{ code: number; stdout: string; stderr: string; spawnError?: NodeJS.ErrnoException }>(
    (resolve) => {
      execFile(
        bin,
        argv,
        { timeout: 55_000, signal, maxBuffer: 8 * 1024 * 1024, windowsHide: true },
        (error, stdout, stderr) => {
          if (error !== null && 'code' in error && (error as NodeJS.ErrnoException).code === 'ENOENT') {
            resolve({ code: 127, stdout: '', stderr: '', spawnError: error as NodeJS.ErrnoException })
            return
          }
          const code =
            error !== null && typeof (error as { code?: unknown }).code === 'number'
              ? ((error as { code: number }).code as number)
              : 0
          resolve({ code, stdout: String(stdout), stderr: String(stderr) })
        },
      )
    },
  )
  if (outcome.spawnError !== undefined) return MISSING_BINARY_MESSAGE
  const stdout = outcome.stdout.trim()
  const stderr = outcome.stderr.trim()
  if (outcome.code === 0) {
    if (stdout.length > 0) return stdout
    return stderr.length > 0 ? stderr : '{}'
  }
  const body = stdout.length > 0 ? stdout : stderr
  return `macos-cu exited with code ${outcome.code}${body.length > 0 ? `:\n${body}` : ' (no output).'}${
    stderr.length > 0 && stdout.length > 0 ? `\nstderr:\n${stderr}` : ''
  }`
}

/** Append `--flag value` only when the value is defined. */
export function pushOpt(argv: string[], flag: string, value: string | number | undefined): void {
  if (value !== undefined) argv.push(flag, String(value))
}

/** Append a boolean switch only when true. */
export function pushFlag(argv: string[], flag: string, value: boolean | undefined): void {
  if (value === true) argv.push(flag)
}
