# VS Code integration

`.vscode/tasks.json` is intentionally thin: it calls the public `ws` CLI and does not import domain modules. This keeps editor integration replaceable and makes the same commands usable from automation. Add shortcuts by composing these commands rather than writing state directly.
