/**
 * dsh bundle bridging DeepSeek Harness to the `macos-cu` CLI (AX-first
 * computer use on macOS). Registers five focused tools that shell out with an
 * argument array and return the CLI's JSON output.
 * @module dsh-macos-computer-use
 */

import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { pushFlag, pushOpt, runMacosCu } from './macosCu.js'

export const name = 'macos-computer-use'

export const inject = ['tools']

const AX_FIRST =
  ' AX-first: locate elements via macos_ax_find and use the returned geometry — use instead of guessing coordinates from a screenshot.'

const OUTPUT = {
  schema: { type: 'string' } as const,
  render: (_args: unknown, value: string) => [{ type: 'text' as const, text: value }],
}

const doctor = defineTool({
  name: 'macos_cu_doctor',
  description: `Run \`macos-cu doctor\` and return its JSON diagnostics (TCC permissions, displays, dependencies, Jev). Call this first when the environment may lack Accessibility/Screen Recording grants.${AX_FIRST}`,
  parameters: {},
  output: OUTPUT,
  async execute(_args, exec) {
    return runMacosCu(['doctor'], exec.signal)
  },
})

const axFind = defineTool({
  name: 'macos_ax_find',
  description: `Semantic AX-tree lookup: \`macos-cu ax find\` (exact element geometry) or \`macos-cu ax tree\` (subtree dump). Returns JSON with each element's role/title/value plus exact screen geometry. Always prefer this over screenshots for locating UI elements — use instead of guessing coordinates from a screenshot.${AX_FIRST}`,
  parameters: {
    app: { type: 'string', description: 'App name or bundle id, e.g. "Google Chrome" or com.apple.finder.' },
    role: { type: 'string', description: 'AX role filter, e.g. AXButton, AXTextField.' },
    title: { type: 'string', description: 'Substring of the element title/name to match.' },
    mode: {
      type: 'string',
      enum: ['find', 'tree'],
      description: 'find returns matches with geometry; tree dumps the subtree. Default find.',
    },
    depth: { type: 'integer', description: 'Tree walk depth (tree mode).' },
    max: { type: 'integer', description: 'Maximum elements to return.' },
  },
  output: OUTPUT,
  async execute(args, exec) {
    const argv = ['ax', args.mode ?? 'find']
    pushOpt(argv, '--app', args.app)
    pushOpt(argv, '--role', args.role)
    pushOpt(argv, '--title', args.title)
    pushOpt(argv, '--depth', args.depth)
    pushOpt(argv, '--max', args.max)
    return runMacosCu(argv, exec.signal)
  },
})

const axPress = defineTool({
  name: 'macos_ax_press',
  description: `Native AX action with read-back verification: \`macos-cu ax press\` (AXPress on a button/menu item) or \`macos-cu ax setvalue\` (set a text field value, clipboard-safe for CJK). Returns JSON with verified/state_changed/readback. When verified is false, fall back to macos_input_click — never guess from a screenshot.${AX_FIRST}`,
  parameters: {
    action: {
      type: 'string',
      required: true,
      enum: ['press', 'setvalue'],
      description: 'press activates the element; setvalue writes text into it.',
    },
    app: { type: 'string', description: 'App name or bundle id.' },
    role: { type: 'string', description: 'AX role filter, e.g. AXButton, AXTextField.' },
    title: { type: 'string', description: 'Substring of the element title/name to match.' },
    text: { type: 'string', description: 'Text to write (required for setvalue).' },
  },
  output: OUTPUT,
  async execute(args, exec) {
    if (args.action === 'setvalue' && (args.text === undefined || args.text.length === 0)) {
      throw new Error('macos_ax_press: text is required when action is "setvalue"')
    }
    const argv = ['ax', args.action]
    pushOpt(argv, '--app', args.app)
    pushOpt(argv, '--role', args.role)
    pushOpt(argv, '--title', args.title)
    pushOpt(argv, '--text', args.text)
    return runMacosCu(argv, exec.signal)
  },
})

const inputClick = defineTool({
  name: 'macos_input_click',
  description: `Window-scoped click that never moves the user's cursor: \`macos-cu input click\`. Prefer coordinates from macos_ax_find — use instead of guessing coordinates from a screenshot. Supports target validation via --expect (pid:wid:x:y:w:h refuses to act when the window moved).`,
  parameters: {
    x: { type: 'number', required: true, description: 'Screen x in AX/CoreGraphics points.' },
    y: { type: 'number', required: true, description: 'Screen y in AX/CoreGraphics points.' },
    window_id: { type: 'integer', description: 'Target window id from `input windows` (window-relative click).' },
    app: { type: 'string', description: 'App name or bundle id to scope the click.' },
    button: {
      type: 'string',
      enum: ['left', 'right', 'middle'],
      description: 'Mouse button. Default left.',
    },
    count: { type: 'integer', description: 'Click count (2 for double-click).' },
    show: { type: 'boolean', description: 'Show a visual overlay where the agent acted.' },
    expect: {
      type: 'string',
      description: 'Target signature pid:wid:x:y:w:h; refuses to act on mismatch (exit 5).',
    },
  },
  output: OUTPUT,
  async execute(args, exec) {
    const argv = ['input', 'click', '--x', String(args.x), '--y', String(args.y)]
    pushOpt(argv, '--window-id', args.window_id)
    pushOpt(argv, '--app', args.app)
    pushOpt(argv, '--button', args.button)
    pushOpt(argv, '--count', args.count)
    pushFlag(argv, '--show', args.show)
    pushOpt(argv, '--expect', args.expect)
    return runMacosCu(argv, exec.signal)
  },
})

const shot = defineTool({
  name: 'macos_shot',
  description: `Screenshots for verification only (always blank-frame-checked): \`macos-cu shot capture|check|windows\`. Capture writes a PNG and returns a JSON verdict; check classifies an existing file (ok/all_black/all_white/uniform). Locate elements with macos_ax_find first — screenshots verify, they do not target.`,
  parameters: {
    action: {
      type: 'string',
      required: true,
      enum: ['capture', 'check', 'windows'],
      description: 'capture takes a screenshot; check classifies a file; windows lists capturable windows.',
    },
    app: { type: 'string', description: 'App name to capture.' },
    out: { type: 'string', description: 'Output PNG path for capture (e.g. /tmp/shot.png).' },
    file: { type: 'string', description: 'Image path for check.' },
    window_id: { type: 'integer', description: 'Window id to capture.' },
    region: { type: 'string', description: 'Crop region as x,y,w,h.' },
  },
  output: OUTPUT,
  async execute(args, exec) {
    const argv = ['shot', args.action]
    pushOpt(argv, '--app', args.app)
    pushOpt(argv, '--out', args.out)
    pushOpt(argv, '--file', args.file)
    pushOpt(argv, '--window-id', args.window_id)
    pushOpt(argv, '--region', args.region)
    return runMacosCu(argv, exec.signal)
  },
})

/** Register the macos-cu bridge tools. Tool registrations auto-dispose on unload. */
export function apply(ctx: Context): void {
  ctx.tools.register(doctor)
  ctx.tools.register(axFind)
  ctx.tools.register(axPress)
  ctx.tools.register(inputClick)
  ctx.tools.register(shot)
}
