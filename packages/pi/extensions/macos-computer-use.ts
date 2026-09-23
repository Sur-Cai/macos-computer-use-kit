/**
 * macOS computer use for pi, backed by the `macos-cu` CLI.
 *
 * Every tool in this file is a thin bridge to `macos-cu`:
 *   - arguments are handed to the CLI as an argv array via `execFile`
 *     (`shell: false`), so model-supplied text can never reach a shell;
 *   - the CLI's JSON output is returned to the model verbatim, with pi's
 *     standard head-truncation applied so huge AX trees cannot flood context;
 *   - a missing binary produces an actionable install message instead of a
 *     stack trace.
 *
 * Prerequisite: `pip install macos-computer-use-kit`
 */

import { execFile } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";

import { StringEnum } from "@earendil-works/pi-ai";
import {
	DEFAULT_MAX_BYTES,
	DEFAULT_MAX_LINES,
	formatSize,
	truncateHead,
} from "@earendil-works/pi-coding-agent";
import type { AgentToolResult, ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const BIN = "macos-cu";

/**
 * Resolve the CLI lazily, at call time:
 *   1. `MACOS_CU_BIN` — explicit override;
 *   2. a well-known install location (pip/pipx put it in ~/.local/bin; this
 *      repo's ./install.sh puts it in ~/.local/share/macos-computer-use/venv);
 *   3. `macos-cu` on PATH.
 *
 * GUI-launched agents do not inherit an interactive shell's PATH, which is why
 * steps 1-2 exist rather than relying on PATH alone.
 */
function resolveBinary(): string {
	const override = process.env["MACOS_CU_BIN"]?.trim();
	if (override) return override;
	const candidates = [
		join(homedir(), ".local", "bin", BIN),
		join(homedir(), ".local", "share", "macos-computer-use", "venv", "bin", BIN),
	];
	for (const candidate of candidates) {
		if (existsSync(candidate)) return candidate;
	}
	return BIN;
}

const INSTALL_HINT = [
	`${BIN} CLI not found (checked MACOS_CU_BIN, ~/.local/bin, ~/.local/share/macos-computer-use/venv/bin, and PATH).`,
	"",
	"Install it with:",
	"  pip install macos-computer-use-kit",
	"",
	"If your Python is managed by the system, use pipx instead:",
	"  pipx install macos-computer-use-kit",
	"",
	"Then run `macos-cu doctor` once and grant Accessibility + Screen Recording",
	"to the app that runs pi (Terminal, iTerm, or the pi app).",
	"",
	"If it is installed somewhere unusual, set MACOS_CU_BIN to its absolute path",
	"and restart pi.",
].join("\n");

interface CliResult {
	args: string[];
	code: number | null;
	stdout: string;
	stderr: string;
	/** Parsed stdout, when the CLI emitted JSON there. */
	json: unknown;
	/** Parsed stderr, when the CLI emitted JSON there (the CLI reports errors on stderr). */
	errorJson: unknown;
	missing: boolean;
	timedOut: boolean;
	aborted: boolean;
}

interface CliDetails {
	command: string;
	args: string[];
	exitCode: number | null;
	missing?: boolean;
	timedOut?: boolean;
	aborted?: boolean;
	json?: unknown;
}

function parseJson(text: string): unknown {
	const trimmed = text.trim();
	if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return undefined;
	try {
		return JSON.parse(trimmed);
	} catch {
		return undefined;
	}
}

/** Normalize a child-process chunk, which is typed as heavily overloaded. */
function asText(value: unknown): string {
	if (typeof value === "string") return value;
	if (value == null) return "";
	if (value instanceof Uint8Array) return Buffer.from(value).toString("utf8");
	return String(value);
}

/**
 * Run `macos-cu` with an argv array. `shell` is never used, so no argument can
 * be interpreted by a shell. Resolves for any exit code; `missing` reports
 * ENOENT and `aborted` reports cancellation through the tool's signal.
 */
function runCli(
	args: string[],
	options: { signal?: AbortSignal; timeoutMs?: number; stdin?: string } = {},
): Promise<CliResult> {
	return new Promise((resolve) => {
		let settled = false;
		const settle = (partial: Partial<CliResult>) => {
			if (settled) return;
			settled = true;
			resolve({
				args,
				code: null,
				stdout: "",
				stderr: "",
				json: undefined,
				errorJson: undefined,
				missing: false,
				timedOut: false,
				aborted: false,
				...partial,
			});
		};

		let child: ReturnType<typeof execFile>;
		try {
			child = execFile(
				resolveBinary(),
				args,
				{
					signal: options.signal,
					timeout: options.timeoutMs ?? 60_000,
					maxBuffer: 16 * 1024 * 1024,
					encoding: "utf8",
				},
				(error, stdout, stderr) => {
					const out = asText(stdout);
					const err = asText(stderr);
					const failure = error as (NodeJS.ErrnoException & { killed?: boolean }) | null;
					const rawCode = failure?.code;
					const spawnFailed = typeof rawCode === "string";
					const aborted = options.signal?.aborted === true;
					const killed = failure?.killed === true;

					settle({
						code: spawnFailed ? null : typeof rawCode === "number" ? rawCode : error ? 1 : 0,
						stdout: out,
						stderr: err,
						json: parseJson(out),
						errorJson: parseJson(err),
						missing: rawCode === "ENOENT",
						timedOut: killed && !aborted,
						aborted,
					});
				},
			);
		} catch (error) {
			const rawCode = (error as NodeJS.ErrnoException | null)?.code;
			settle({
				missing: rawCode === "ENOENT",
				stderr: String((error as Error)?.message ?? error),
				aborted: options.signal?.aborted === true,
			});
			return;
		}

		// `jev` reads a JSON payload from stdin and would otherwise wait forever.
		child.stdin?.end(options.stdin ?? "");
	});
}

/** Render a CLI run as a pi tool result: JSON as-is, non-zero exits called out. */
function formatCli(prefix: string, cli: CliResult): AgentToolResult<CliDetails> {
	const details: CliDetails = {
		command: [BIN, ...cli.args].join(" "),
		args: cli.args,
		exitCode: cli.code,
		missing: cli.missing,
		timedOut: cli.timedOut,
		aborted: cli.aborted,
		json: cli.json ?? cli.errorJson,
	};

	if (cli.aborted) {
		return { content: [{ type: "text", text: "Cancelled" }], details };
	}

	if (cli.missing) {
		return { content: [{ type: "text", text: INSTALL_HINT }], details };
	}

	if (cli.timedOut) {
		return {
			content: [
				{
					type: "text",
					text: `${details.command} timed out. Narrow the request (for example a smaller --max, or a specific --role/--title) and retry.`,
				},
			],
			details,
		};
	}

	const payload = cli.json ?? cli.errorJson;
	if (payload === undefined && cli.code !== 0) {
		// Real breakage (Python traceback, argparse usage error): surface it as a tool error.
		throw new Error(
			`${details.command} failed with exit code ${cli.code ?? "?"}: ${(cli.stderr || cli.stdout).trim() || "no output"}`,
		);
	}

	let text =
		cli.json !== undefined
			? JSON.stringify(cli.json, null, 2)
			: cli.stdout.trim() || (cli.errorJson !== undefined ? JSON.stringify(cli.errorJson, null, 2) : "");

	if (cli.code !== 0) {
		text += `\n\n[${BIN} exited with code ${cli.code}]`;
		if (cli.json === undefined && cli.stderr.trim()) text += `\n${cli.stderr.trim()}`;
	}

	// pi requires tools to bound their output; AX trees can be large.
	const truncation = truncateHead(text, { maxLines: DEFAULT_MAX_LINES, maxBytes: DEFAULT_MAX_BYTES });
	if (truncation.truncated) {
		const full = writeFullOutput(prefix, text);
		text = truncation.content;
		text += `\n\n[${prefix} output truncated: ${truncation.outputLines} of ${truncation.totalLines} lines`;
		text += ` (${formatSize(truncation.outputBytes)} of ${formatSize(truncation.totalBytes)}).`;
		text += full ? ` Full output saved to: ${full}]` : "]";
	}

	return { content: [{ type: "text", text }], details };
}

function writeFullOutput(prefix: string, text: string): string | undefined {
	try {
		const dir = join(tmpdir(), "macos-cu-output");
		mkdirSync(dir, { recursive: true });
		const file = join(dir, `${prefix.replace(/[^a-zA-Z0-9_-]+/g, "-")}-${Date.now()}.txt`);
		writeFileSync(file, text, "utf8");
		return file;
	} catch {
		return undefined;
	}
}

function targetArgs(app: string | undefined, pid: number | undefined): string[] {
	const args: string[] = [];
	if (app) args.push("--app", app);
	if (pid !== undefined) args.push("--pid", String(pid));
	return args;
}

export default function macosComputerUse(pi: ExtensionAPI) {
	pi.registerTool({
		name: "macos_cu_doctor",
		label: "macOS CU: doctor",
		description:
			"Diagnose the macOS computer-use environment: accessibility and screen-recording permissions, display layout, pyobjc dependencies, and optional Jev setup. Run this first when a macos_* tool fails, and before automating a new machine. Exit code 1 with valid JSON only means a permission is still missing; read the hints field.",
		promptSnippet: "Check macOS permissions, displays, dependencies, and Jev setup",
		promptGuidelines: [
			"Use macos_cu_doctor before the first macOS automation on a machine, and again whenever a macos_* tool returns a permission error.",
		],
		parameters: Type.Object({}),
		async execute(_toolCallId, _params, signal) {
			const cli = await runCli(["doctor"], { signal, timeoutMs: 30_000 });
			return formatCli("doctor", cli);
		},
	});

	pi.registerTool({
		name: "macos_ax_find",
		label: "macOS CU: AX find/tree",
		description:
			"Locate a UI element by its accessibility (AX) role and title and get its exact screen geometry (center_screen, size, window). Use this instead of guessing coordinates from a screenshot: read the AX tree, then press or click the element. Modes: 'find' (filtered elements as JSON), 'tree' (broader JSON dump), 'snapshot' (token-efficient text list with stable ids, plus a cache file for resolve), 'resolve' (one element by id from a snapshot cache file).",
		promptSnippet: "Find a macOS UI element by AX role/title and return its exact screen coordinates",
		promptGuidelines: [
			"Use macos_ax_find instead of estimating coordinates from a screenshot, then pass the returned center_screen to macos_input_click.",
		],
		parameters: Type.Object({
			mode: StringEnum(["find", "tree", "snapshot", "resolve"], {
				description:
					"find = filtered elements (default), tree = broader AX dump, snapshot = budgeted text list with ids, resolve = look up an id in a snapshot file",
				default: "find",
			}),
			app: Type.Optional(
				Type.String({
					description: "App name or bundle id (substring match), e.g. 'Finder' or 'com.apple.finder'.",
				}),
			),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
			role: Type.Optional(
				Type.String({ description: "AX role filter, e.g. AXButton, AXTextField, AXStaticText." }),
			),
			title: Type.Optional(
				Type.String({ description: "Substring match on the element's title, description, or value." }),
			),
			max: Type.Optional(Type.Integer({ description: "Cap the number of elements returned (default 120)." })),
			depth: Type.Optional(Type.Integer({ description: "AX tree depth to walk (default 16)." })),
			budget: Type.Optional(
				Type.Integer({ description: "snapshot mode: max characters of list text (default 4000)." }),
			),
			file: Type.Optional(
				Type.String({ description: "snapshot mode: cache file to write; resolve mode: cache file to read." }),
			),
			id: Type.Optional(Type.String({ description: "resolve mode: element id from a snapshot, e.g. 0.1.0.6." })),
			ref: Type.Optional(Type.String({ description: "resolve mode: stable element ref from a snapshot (after '#')." })),
			interactive: Type.Optional(
				Type.Boolean({ description: "Only actionable elements (buttons, fields, links, menu items...)." }),
			),
			diff: Type.Optional(
				Type.String({ description: "snapshot mode: an earlier snapshot file; return only what changed." }),
			),
		}),
		async execute(_toolCallId, params, signal) {
			const target = targetArgs(params.app, params.pid);
			const mode = params.mode ?? "find";

			if (mode === "resolve") {
				if (!params.file || !(params.id || params.ref)) {
					throw new Error("macos_ax_find mode='resolve' needs 'file' (snapshot cache) and 'id' or 'ref'.");
				}
				const args = ["ax", "resolve", "--file", params.file];
				if (params.id) args.push("--id", params.id);
				if (params.ref) args.push("--ref", params.ref);
				const cli = await runCli(args, { signal });
				return formatCli("ax resolve", cli);
			}

			if (mode === "snapshot") {
				const args = ["ax", "snapshot", ...target];
				if (params.budget !== undefined) args.push("--budget", String(params.budget));
				if (params.file) args.push("--file", params.file);
				if (params.depth !== undefined) args.push("--depth", String(params.depth));
				if (params.max !== undefined) args.push("--max", String(params.max));
				if (params.interactive) args.push("--interactive");
				if (params.diff) args.push("--diff", params.diff);
				if (params.role) args.push("--role", params.role);
				if (params.title) args.push("--title", params.title);
				const cli = await runCli(args, { signal, timeoutMs: 90_000 });
				return formatCli("ax snapshot", cli);
			}

			const args = ["ax", mode, ...target, "--json"];
			if (params.role) args.push("--role", params.role);
			if (params.title) args.push("--title", params.title);
			if (params.max !== undefined) args.push("--max", String(params.max));
			if (params.depth !== undefined) args.push("--depth", String(params.depth));
			if (params.interactive) args.push("--interactive");
			const cli = await runCli(args, { signal, timeoutMs: 90_000 });
			return formatCli(`ax ${mode}`, cli);
		},
	});

	pi.registerTool({
		name: "macos_ax_press",
		label: "macOS CU: AX press/setvalue",
		description:
			"Run a native accessibility action on a macOS element and read the result back: 'press' invokes AXPress (buttons, menu items, checkboxes) and 'setvalue' writes text into a text field. The CLI compares the window's visible text and focused element before and after and reports verified true/false. Prefer this over a coordinate click: when verified is false the UI is custom-drawn, and the result carries a hint telling you to fall back.",
		promptSnippet: "Press a macOS element or set its value via AX, with read-back verification",
		promptGuidelines: [
			"Prefer macos_ax_press over macos_input_click for standard AX elements; check the returned 'verified' field and fall back to macos_input_click or macos_paste only when it is false.",
		],
		parameters: Type.Object({
			action: StringEnum(["press", "setvalue", "focus", "action", "actions"], {
				description:
					"press = AXPress; setvalue = write text; focus = focus the element; action = run the AX action in 'name'; actions = list the element's AX actions",
			}),
			ref: Type.Optional(Type.String({ description: "Stable element ref from a snapshot (preferred over role/title)." })),
			name: Type.Optional(
				Type.String({ description: "action: AX action name, e.g. AXShowMenu, AXIncrement, AXConfirm." }),
			),
			app: Type.Optional(Type.String({ description: "App name or bundle id (substring match)." })),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
			role: Type.Optional(Type.String({ description: "AX role of the target, e.g. AXButton or AXTextField." })),
			title: Type.Optional(
				Type.String({ description: "Substring match on the element's title/description/value." }),
			),
			text: Type.Optional(Type.String({ description: "Text to write; required when action='setvalue'." })),
		}),
		async execute(_toolCallId, params, signal) {
			const target = targetArgs(params.app, params.pid);
			if (!target.length) throw new Error("macos_ax_press needs 'app' or 'pid'.");

			const args = ["ax", params.action, ...target];
			if (params.ref) args.push("--ref", params.ref);
			if (params.name) args.push("--name", params.name);
			if (params.action === "action" && !params.name) throw new Error("macos_ax_press action='action' needs 'name'.");
			if (params.role) args.push("--role", params.role);
			if (params.title) args.push("--title", params.title);

			if (params.action === "setvalue") {
				if (params.text === undefined) throw new Error("macos_ax_press action='setvalue' needs 'text'.");
				args.push("--text", params.text);
			}

			const cli = await runCli(args, { signal, timeoutMs: 60_000 });
			return formatCli(`ax ${params.action}`, cli);
		},
	});

	pi.registerTool({
		name: "macos_input_windows",
		label: "macOS CU: list windows",
		description:
			"List an app's windows with their window ids, geometry, and the stable target signature (pid:window-id:x:y:w:h) used by the 'expect' guard of macos_input_click. Start here to pick a window, then target it by window_id so all coordinates become window-relative.",
		promptSnippet: "List macOS windows with ids and target signatures",
		parameters: Type.Object({
			app: Type.Optional(
				Type.String({ description: "App name or bundle id (substring match); omit to list every window." }),
			),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
		}),
		async execute(_toolCallId, params, signal) {
			const args = ["input", "windows", ...targetArgs(params.app, params.pid)];
			const cli = await runCli(args, { signal, timeoutMs: 45_000 });
			return formatCli("input windows", cli);
		},
	});

	pi.registerTool({
		name: "macos_input_click",
		label: "macOS CU: click",
		description:
			"Click a point on macOS without moving the user's physical cursor: the event is posted straight to the target process. Use macos_ax_find for the coordinates instead of guessing from a screenshot. Pass window_id to make x/y window-relative (omit it and x/y are screen points). Pass expect with the signature from macos_input_windows to refuse the click when the window moved or lost focus; a mismatch returns {ok:false,reason:'target_changed'} with exit code 5. 'show' draws a transient ring where the agent acted.",
		promptSnippet: "Click a macOS screen or window-relative point without moving the user's cursor",
		promptGuidelines: [
			"Use macos_input_click with coordinates from macos_ax_find; never estimate coordinates from a screenshot.",
			"When clicking inside a specific window, pass both window_id and the expect signature from macos_input_windows so a moved window is refused instead of mis-clicked.",
		],
		parameters: Type.Object({
			x: Type.Integer({ description: "X coordinate: screen points, or window-relative when window_id is set." }),
			y: Type.Integer({ description: "Y coordinate: screen points, or window-relative when window_id is set." }),
			app: Type.Optional(Type.String({ description: "App name or bundle id (substring match)." })),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
			window_id: Type.Optional(Type.Integer({ description: "Target window id; makes x/y window-relative." })),
			button: Type.Optional(
				StringEnum(["left", "right", "middle"], { description: "Mouse button (default left)." }),
			),
			count: Type.Optional(Type.Integer({ description: "Click count, e.g. 2 for a double click." })),
			expect: Type.Optional(
				Type.String({ description: "Expected signature 'pid:wid:x:y:w:h'; a mismatch refuses the click." }),
			),
			show: Type.Optional(Type.Boolean({ description: "Draw a transient visual ring at the click point." })),
		}),
		async execute(_toolCallId, params, signal) {
			const args = ["input", "click", "--x", String(params.x), "--y", String(params.y)];
			if (params.window_id !== undefined) args.push("--window-id", String(params.window_id));
			args.push(...targetArgs(params.app, params.pid));
			if (params.button) args.push("--button", params.button);
			if (params.count !== undefined) args.push("--count", String(params.count));
			if (params.expect) args.push("--expect", params.expect);
			if (params.show) args.push("--show");
			const cli = await runCli(args, { signal, timeoutMs: 45_000 });
			return formatCli("input click", cli);
		},
	});

	pi.registerTool({
		name: "macos_input_key",
		label: "macOS CU: key",
		description:
			"Send a keystroke to a macOS app without moving the user's cursor: pass key as a single character or key name ('t', 'return', 'tab', 'escape', 'f5') and flags as a '+' list ('cmd', 'cmd+shift', 'ctrl+alt'). Prefer keyboard shortcuts over clicking through menus (cmd+l for a URL bar, cmd+f to search). Background keystrokes are accepted by most apps but not all; bring the app forward first when a background key is ignored.",
		promptSnippet: "Send a macOS keystroke or keyboard shortcut to an app",
		parameters: Type.Object({
			key: Type.String({ description: "Key to press, e.g. 't', 'return', 'escape', 'up', 'f5'." }),
			flags: Type.Optional(Type.String({ description: "Modifier list separated by '+', e.g. 'cmd', 'cmd+shift'." })),
			app: Type.Optional(Type.String({ description: "App name or bundle id (substring match)." })),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
		}),
		async execute(_toolCallId, params, signal) {
			const args = ["input", "key", "--key", params.key, ...targetArgs(params.app, params.pid)];
			if (params.flags) args.push("--flags", params.flags);
			const cli = await runCli(args, { signal, timeoutMs: 45_000 });
			return formatCli("input key", cli);
		},
	});

	pi.registerTool({
		name: "macos_paste",
		label: "macOS CU: paste",
		description:
			"Type arbitrary text into a macOS app through the clipboard, restoring the user's clipboard afterwards. Use this for CJK and other non-ASCII text: character-by-character typing gets eaten by input methods, ASCII survives and the rest does not. Takeover (exit 2) and non-consumption (exit 3) are reported explicitly. Read the target field back before sending anything irreversible. mode 'hid' brings the app forward and can be more reliable, at the cost of stealing focus.",
		promptSnippet: "Paste text (including CJK) into a macOS app with clipboard restore",
		promptGuidelines: [
			"Use macos_paste for any non-ASCII text instead of macos_input_key, and re-read the target field with macos_ax_find before sending anything irreversible.",
		],
		parameters: Type.Object({
			text: Type.String({ description: "Text to place in the target's focused field." }),
			app: Type.Optional(Type.String({ description: "App name or bundle id (substring match)." })),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
			mode: Type.Optional(
				StringEnum(["pid", "hid"], {
					description: "pid (default) posts to the process; hid brings the app forward.",
				}),
			),
			wait: Type.Optional(
				Type.Number({ description: "Seconds to wait before checking consumption (default 1.5)." }),
			),
			keep: Type.Optional(
				Type.Boolean({ description: "Leave the pasted text on the clipboard instead of restoring it." }),
			),
		}),
		async execute(_toolCallId, params, signal) {
			const args = ["paste", "--text", params.text, ...targetArgs(params.app, params.pid)];
			if (params.mode) args.push("--mode", params.mode);
			if (params.wait !== undefined) args.push("--wait", String(params.wait));
			if (params.keep) args.push("--keep");
			const waitMs = params.wait !== undefined ? Math.max(0, params.wait) * 1000 : 1500;
			const cli = await runCli(args, { signal, timeoutMs: waitMs + 45_000 });
			return formatCli("paste", cli);
		},
	});

	pi.registerTool({
		name: "macos_shot",
		label: "macOS CU: screenshot",
		description:
			"Screenshots with blank-frame detection. Modes: 'capture' saves a window or region to 'out' and returns a verdict; 'check' analyses an existing image for all_black / all_white / uniform / ok; 'windows' lists capturable windows with ids. Screenshots are for verification only — use macos_ax_find for targeting. Never reason about a frame whose verdict is all_black: that means missing Screen Recording permission or full occlusion, not a black UI.",
		promptSnippet: "Capture or blank-check a macOS screenshot to verify state after acting",
		promptGuidelines: [
			"Use macos_shot only to verify that an action changed the screen; never reason about a frame whose verdict is all_black.",
		],
		parameters: Type.Object({
			command: StringEnum(["capture", "check", "windows", "displays", "annotate"], {
				description:
					"capture = save a window/region image; check = blank-frame analysis; windows = list capturable windows; displays = display layout; annotate = numbered set-of-mark boxes on an app's interactive elements",
			}),
			crop: Type.Optional(Type.String({ description: "capture: 'x,y,w,h' screen rect to zoom into." })),
			out: Type.Optional(Type.String({ description: "capture: output file path, e.g. /tmp/shot.png." })),
			file: Type.Optional(Type.String({ description: "check: existing image to analyse." })),
			app: Type.Optional(Type.String({ description: "App name or bundle id (substring match)." })),
			window_id: Type.Optional(Type.Integer({ description: "capture: window id to capture." })),
			region: Type.Optional(Type.String({ description: "capture: 'x,y,w,h' screen region." })),
		}),
		async execute(_toolCallId, params, signal) {
			if (params.command === "check") {
				if (!params.file) throw new Error("macos_shot command='check' needs 'file'.");
				const cli = await runCli(["shot", "check", "--file", params.file], { signal });
				return formatCli("shot check", cli);
			}

			if (params.command === "displays") {
				const cli = await runCli(["shot", "displays"], { signal });
				return formatCli("shot displays", cli);
			}

			if (params.command === "annotate") {
				if (!params.app) throw new Error("macos_shot command='annotate' needs 'app'.");
				const args = ["shot", "annotate", "--app", params.app];
				if (params.out) args.push("--out", params.out);
				const cli = await runCli(args, { signal, timeoutMs: 90_000 });
				return formatCli("shot annotate", cli);
			}

			if (params.command === "windows") {
				const args = ["shot", "windows"];
				if (params.app) args.push("--app", params.app);
				const cli = await runCli(args, { signal, timeoutMs: 45_000 });
				return formatCli("shot windows", cli);
			}

			const args = ["shot", "capture"];
			if (params.out) args.push("--out", params.out);
			if (params.app) args.push("--app", params.app);
			if (params.window_id !== undefined) args.push("--window-id", String(params.window_id));
			if (params.region) args.push("--region", params.region);
			if (params.crop) args.push("--crop", params.crop);
			const cli = await runCli(args, { signal, timeoutMs: 60_000 });
			return formatCli("shot capture", cli);
		},
	});

	pi.registerTool({
		name: "macos_jev_guard",
		label: "macOS CU: Jev guard",
		description:
			"Optional TypeSafe Jev semantic guards for macOS, for the moment right before an irreversible action. 'guard' fans one request out into four calibrated judgments about expected versus observed state (right_target, input_ok, blocker, next_action) plus a decision; 'select' picks one candidate element id from a list with a confidence gate and a 'none' escape hatch. Use only for semantic identity/state/effect questions that ordinary code cannot decide — never for blank-frame detection or signature comparison. Requires TYPESAFE_API_KEY or ~/.config/typesafe/api_key. The request payload is sent on stdin.",
		promptSnippet: "Ask Jev (optional) for a calibrated judgment before an irreversible macOS action",
		promptGuidelines: [
			"Use macos_jev_guard only before irreversible actions such as sending a message, and proceed only when blocker is 'none' and both probabilities clear 0.85.",
		],
		parameters: Type.Object({
			command: StringEnum(["guard", "select"], {
				description: "guard = pre-action judgment; select = pick an element id from candidates",
			}),
			payload: Type.String({
				description:
					'JSON request for the CLI stdin. guard: {"task":...,"expected":{...},"observed":{...}}. select: {"goal":...,"candidates":[{"id":...,"text":...}]}.',
			}),
		}),
		async execute(_toolCallId, params, signal) {
			let parsed: unknown;
			try {
				parsed = JSON.parse(params.payload);
			} catch (error) {
				throw new Error(`macos_jev_guard 'payload' is not valid JSON: ${(error as Error).message}`);
			}
			if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
				throw new Error("macos_jev_guard 'payload' must be a JSON object.");
			}
			if (params.command === "guard" && !(parsed as { task?: unknown }).task) {
				throw new Error("macos_jev_guard command='guard' needs a 'task' field in the payload.");
			}
			if (params.command === "select" && !Array.isArray((parsed as { candidates?: unknown }).candidates)) {
				throw new Error("macos_jev_guard command='select' needs a 'candidates' array in the payload.");
			}

			const cli = await runCli(["jev", params.command], {
				signal,
				stdin: JSON.stringify(parsed),
				timeoutMs: 120_000,
			});
			return formatCli(`jev ${params.command}`, cli);
		},
	});
	pi.registerTool({
		name: "macos_type",
		label: "macOS CU: type",
		description:
			"Type text into the focused field of a macOS app with Unicode keyboard events: CJK, emoji, and accented text arrive intact, the clipboard is untouched, and the user's cursor does not move. Newlines are sent as Return (in chat apps that sends). Refused while a password field holds Secure Event Input. For very long text prefer macos_paste.",
		promptSnippet: "Type Unicode text (CJK/emoji safe) into a macOS app",
		parameters: Type.Object({
			text: Type.String({ description: "Text to type." }),
			app: Type.Optional(Type.String({ description: "App name or bundle id." })),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
		}),
		async execute(_toolCallId, params, signal) {
			const args = ["input", "type", "--text", params.text, ...targetArgs(params.app, params.pid)];
			const cli = await runCli(args, { signal, timeoutMs: 60_000 + params.text.length * 20 });
			return formatCli("input type", cli);
		},
	});

	pi.registerTool({
		name: "macos_pointer",
		label: "macOS CU: scroll/drag/hover",
		description:
			"Pointer gestures posted to the target process (the user's cursor does not move): 'scroll' at x/y (dy > 0 down, dx > 0 right), 'drag' from x/y to to_x/to_y through intermediate points (sliders, reordering, selections), 'hover' to reveal tooltips or hover menus. Pass window_id to make coordinates window-relative.",
		promptSnippet: "Scroll, drag, or hover in a macOS app",
		parameters: Type.Object({
			gesture: StringEnum(["scroll", "drag", "hover"], { description: "Which gesture to perform." }),
			x: Type.Integer({ description: "X in screen points (window-relative with window_id)." }),
			y: Type.Integer({ description: "Y in screen points (window-relative with window_id)." }),
			to_x: Type.Optional(Type.Integer({ description: "drag: destination x." })),
			to_y: Type.Optional(Type.Integer({ description: "drag: destination y." })),
			dy: Type.Optional(Type.Integer({ description: "scroll: vertical amount, positive = down (default 5)." })),
			dx: Type.Optional(Type.Integer({ description: "scroll: horizontal amount, positive = right." })),
			app: Type.Optional(Type.String({ description: "App name or bundle id." })),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
			window_id: Type.Optional(Type.Integer({ description: "Target window id; makes coordinates window-relative." })),
		}),
		async execute(_toolCallId, params, signal) {
			const args = ["input", params.gesture, "--x", String(params.x), "--y", String(params.y)];
			args.push(...targetArgs(params.app, params.pid));
			if (params.window_id !== undefined) args.push("--window-id", String(params.window_id));
			if (params.gesture === "drag") {
				if (params.to_x === undefined || params.to_y === undefined) {
					throw new Error("macos_pointer gesture='drag' needs 'to_x' and 'to_y'.");
				}
				args.push("--to-x", String(params.to_x), "--to-y", String(params.to_y));
			}
			if (params.gesture === "scroll") {
				if (params.dy !== undefined) args.push("--amount", String(params.dy));
				if (params.dx !== undefined) args.push("--dx", String(params.dx));
			}
			const cli = await runCli(args, { signal, timeoutMs: 45_000 });
			return formatCli(`input ${params.gesture}`, cli);
		},
	});

	pi.registerTool({
		name: "macos_app",
		label: "macOS CU: apps",
		description:
			"Manage macOS apps: 'list' running apps, 'launch' (and wait until it is running), 'activate' (bring to front, verified), 'hide', 'quit' (force for a hung app), or 'open' a URL or file, optionally with a specific app.",
		promptSnippet: "List, launch, activate, hide, or quit macOS apps; open URLs and files",
		parameters: Type.Object({
			action: StringEnum(["list", "launch", "activate", "hide", "quit", "open"], { description: "What to do." }),
			app: Type.Optional(Type.String({ description: "App name or bundle id." })),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
			target: Type.Optional(Type.String({ description: "open: URL or file path." })),
			background: Type.Optional(Type.Boolean({ description: "launch/open without activating." })),
			force: Type.Optional(Type.Boolean({ description: "quit: force terminate." })),
		}),
		async execute(_toolCallId, params, signal) {
			const args = ["app", params.action, ...targetArgs(params.app, params.pid)];
			if (params.target) args.push("--target", params.target);
			if (params.background) args.push("--background");
			if (params.force) args.push("--force");
			const cli = await runCli(args, { signal, timeoutMs: 45_000 });
			return formatCli(`app ${params.action}`, cli);
		},
	});

	pi.registerTool({
		name: "macos_window",
		label: "macOS CU: windows",
		description:
			"Manage an app's windows through accessibility: 'list' (title, position, size, main/focused/minimized/modal), 'move', 'resize', 'minimize', 'restore', 'raise', 'focus', 'close', or toggle 'fullscreen'. Pick a window by title substring or index; the default is the focused window.",
		promptSnippet: "Move, resize, focus, minimize, or close a macOS window",
		parameters: Type.Object({
			action: StringEnum(["list", "move", "resize", "minimize", "restore", "raise", "focus", "close", "fullscreen"], {
				description: "What to do.",
			}),
			app: Type.Optional(Type.String({ description: "App name or bundle id." })),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
			title: Type.Optional(Type.String({ description: "Window title substring." })),
			index: Type.Optional(Type.Integer({ description: "Window index from action='list'." })),
			x: Type.Optional(Type.Integer({ description: "move: new x." })),
			y: Type.Optional(Type.Integer({ description: "move: new y." })),
			width: Type.Optional(Type.Integer({ description: "resize: new width." })),
			height: Type.Optional(Type.Integer({ description: "resize: new height." })),
		}),
		async execute(_toolCallId, params, signal) {
			const args = ["window", params.action, ...targetArgs(params.app, params.pid)];
			if (params.title) args.push("--title", params.title);
			if (params.index !== undefined) args.push("--index", String(params.index));
			if (params.x !== undefined) args.push("--x", String(params.x));
			if (params.y !== undefined) args.push("--y", String(params.y));
			if (params.width !== undefined) args.push("--width", String(params.width));
			if (params.height !== undefined) args.push("--height", String(params.height));
			const cli = await runCli(args, { signal, timeoutMs: 45_000 });
			return formatCli(`window ${params.action}`, cli);
		},
	});

	pi.registerTool({
		name: "macos_menu",
		label: "macOS CU: menu bar",
		description:
			"Use an app's menu bar by path, e.g. 'File > Export…', without guessing shortcuts and without bringing the app forward. 'list' shows the items at a path (enabled state, shortcut, submenu); 'select' presses the item.",
		promptSnippet: "List or select a macOS menu-bar item by path",
		parameters: Type.Object({
			action: StringEnum(["list", "select"], { description: "list items or select one." }),
			path: Type.Optional(Type.String({ description: "Menu path separated by '>', e.g. 'View > Show Sidebar'." })),
			app: Type.Optional(Type.String({ description: "App name or bundle id." })),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
		}),
		async execute(_toolCallId, params, signal) {
			const args = ["menu", params.action, ...targetArgs(params.app, params.pid)];
			if (params.path) args.push("--path", params.path);
			const cli = await runCli(args, { signal, timeoutMs: 45_000 });
			return formatCli(`menu ${params.action}`, cli);
		},
	});

	pi.registerTool({
		name: "macos_ocr",
		label: "macOS CU: OCR",
		description:
			"On-device OCR (Apple Vision) of an app window or screen region, returning each text line with its screen rect and center_screen. Pass 'text' to return only matches. Use when the accessibility tree is empty (games, canvas, custom-drawn UI); prefer macos_ax_find otherwise.",
		promptSnippet: "Find text on screen with on-device OCR when accessibility is empty",
		parameters: Type.Object({
			app: Type.Optional(Type.String({ description: "App whose main window to read." })),
			window_id: Type.Optional(Type.Integer({ description: "Window id to read." })),
			region: Type.Optional(Type.String({ description: "'x,y,w,h' screen region to read." })),
			text: Type.Optional(Type.String({ description: "Only return items containing this text." })),
			languages: Type.Optional(Type.String({ description: "Recognition languages, e.g. 'zh-Hans,en-US'." })),
		}),
		async execute(_toolCallId, params, signal) {
			const args = ["ocr"];
			if (params.app) args.push("--app", params.app);
			if (params.window_id !== undefined) args.push("--window-id", String(params.window_id));
			if (params.region) args.push("--region", params.region);
			if (params.text) args.push("--text", params.text);
			if (params.languages) args.push("--lang", params.languages);
			const cli = await runCli(args, { signal, timeoutMs: 90_000 });
			return formatCli("ocr", cli);
		},
	});

	pi.registerTool({
		name: "macos_wait",
		label: "macOS CU: wait",
		description:
			"Wait until an element (by ref, or role/title, optionally containing 'value') appears in an app — or with gone=true, disappears. Use after actions that load or animate instead of sleeping. Exit code 7 on timeout.",
		promptSnippet: "Wait for a macOS UI element to appear or disappear",
		parameters: Type.Object({
			app: Type.Optional(Type.String({ description: "App name or bundle id." })),
			pid: Type.Optional(Type.Integer({ description: "Target a specific process id instead of 'app'." })),
			ref: Type.Optional(Type.String({ description: "Stable element ref from a snapshot." })),
			role: Type.Optional(Type.String({ description: "AX role filter." })),
			title: Type.Optional(Type.String({ description: "Title/description/value substring." })),
			value: Type.Optional(Type.String({ description: "The element's value must contain this." })),
			gone: Type.Optional(Type.Boolean({ description: "Wait for the element to disappear." })),
			timeout: Type.Optional(Type.Number({ description: "Seconds (default 10)." })),
		}),
		async execute(_toolCallId, params, signal) {
			const args = ["ax", "wait", ...targetArgs(params.app, params.pid)];
			if (params.ref) args.push("--ref", params.ref);
			if (params.role) args.push("--role", params.role);
			if (params.title) args.push("--title", params.title);
			if (params.value) args.push("--value", params.value);
			if (params.gone) args.push("--gone");
			const timeout = params.timeout ?? 10;
			args.push("--timeout", String(timeout));
			const cli = await runCli(args, { signal, timeoutMs: (timeout + 30) * 1000 });
			return formatCli("ax wait", cli);
		},
	});
}
