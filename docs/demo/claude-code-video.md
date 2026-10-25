# 60-second demo: ContextSmith inside Claude Code

Record on Windows with **Win + Alt + R** (Xbox Game Bar) or OBS; on macOS with
**Cmd + Shift + 5**. Use a dark terminal, font size 16+, window about 1280×720.

## Before recording (not on camera)

```bash
pipx install "contextsmith[semantic]"
git clone https://github.com/pallets/flask && cd flask
ctxsmith index                       # first run downloads the small embedding model
claude mcp add contextsmith -- ctxsmith serve --path "$(pwd)"
```

Open a new terminal in `flask/` and clear it.

## Shot list

| Time | On screen | Say / caption |
|---|---|---|
| 0–5 s | Title card or the README header | "ContextSmith: the best code context per token for coding agents." |
| 5–12 s | `claude mcp list` showing `contextsmith ✓ connected` | "It plugs into Claude Code over MCP. Everything runs locally." |
| 12–35 s | Start `claude`, type: *"Use contextsmith get_context with a 3000-token budget to find where Flask checks blueprint names, then tell me what happens if a name contains a dot."* Let it call the tool; expand the tool result for a second. | "One call returns the right functions, ranked and packed into 3,000 tokens: no grepping, no whole files." |
| 35–48 s | Type: *"What would break if I changed url_for? Use contextsmith impact."* | "The call graph shows every caller: what a change could break." |
| 48–55 s | Browser: the README's Results table | "Measured on 114 real Django issues it never saw during tuning." |
| 55–60 s | `github.com/RahulSankhla312/contextsmith` | "Open source, MIT. Link below." |

## Tips

- Do one dry run first so the model files are cached and answers come quickly.
- Trim waiting time in any editor (Clipchamp on Windows is built in), keep it under 60 s.
- Export 1080p MP4 for LinkedIn and X; a GIF of the 12–35 s part works well in the README.
