# staticcheck-mcp

Here's how to get the most out of staticcheck-mcp when you're working with Go code. These guidelines are for both AI assistants and human users, so you can spot and fix issues as you go.

---

## Tool Reference

### `staticcheck-mcp.checks`

Use staticcheck to run static analysis on one or more Go source files. You'll get back clear, structured results.

Parameter Type Required What it does

- **paths** (`list[str]`, required): Paths to files or directories you want to check. Use absolute or relative paths—mix files and folders as needed.
- **recursive** (`bool`, optional, default: `false`): If true, checks all subdirectories inside any folder you include in paths.
- **checks** (`str`, optional): List of check IDs, separated by commas. For example: "all,-ST1000" or "SA1006,SA4006". Leave this blank to use the default set.

What you get back: An AnalysisResult object with details about the findings.

Example:

```json
{
  "success": true,
  "findings": [
    {
      "file": "pkg/server.go",
      "line": 42,
      "column": 5,
      "message": "this value of err is never used",
      "code": "SA4006"
    }
  ]
}
```

- If success is false, staticcheck didn't run at all—maybe it's not installed, timed out, or there's a permissions problem.
- If success is true and findings isn't empty, the tool ran fine but found issues.
- Sometimes you'll see findings with an empty file and no code—that means the error is coming from the tool itself, not your code (for example: "staticcheck error: …").

---

## When to Run Checks

Always use checks in these situations:

- Right after you create, change, or refactor any .go file.
- When you fix an import error, type error, or build failure in a Go file.
- Before you call any Go-related task “done.”
- If someone asks for a quality or correctness review on Go code.

## Here's when checks works best

You're pointing it at real, valid Go files. If there are build errors, static analysis won't work—staticcheck only runs on code it can actually parse.

- You're pointing it at real, valid Go files. If there are build errors, static analysis won't work—staticcheck only runs on code it can actually parse.
- Your project has a `go.mod` and `go.sum`, and dependencies are up to date. If the modules aren't set up, staticcheck will bail with a module-resolution error.
- You're working inside the module root directory, so package-level checks (like SA, S1, or ST families) can figure out package relationships.
- Targeting a single package or just a few files is faster and usually gives more useful results than scanning your whole repo in one go.

---

## Usage Examples

```python
# Check a single file
checks(paths=["./pkg/file.go"])

# Check a whole package directory (not recursive)
checks(paths=["./pkg"])

# Check the whole repo, including every subdirectory
checks(paths=["./"], recursive=True)

# Check a mix of files and folders
checks(paths=["cmd/main.go", "internal/"], recursive=True)

# Only run a specific family of checks
checks(paths=["./pkg"], checks="SA")

# Run all checks, but skip a noisy one
checks(paths=["./pkg"], checks="all,-ST1000")
```

---

## Environment Variables

Tweak these environment variables to control how the MCP server behaves. Make sure to set them before starting the server.

Variable Default What it controls

| Variable                    | Default | What it controls                                                                                                                             |
| --------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| STATICHECK_MCP_TIMEOUT      | 10      | How long staticcheck can run per file (in seconds). For big files or projects with lots of dependencies, bump this up.                       |
| STATICHECK_MCP_MAX_FINDINGS | 10000   | The max number of findings you'll get back in a single call. This stops your terminal from flooding if you have a huge codebase.             |
| STATICHECK_MCP_EXECUTOR     | thread  | The concurrency model: use thread (ThreadPoolExecutor) for most work. If you hit GIL bottlenecks, try process instead (ProcessPoolExecutor). |

---

## Reviewing and Reporting Results

- Always report each finding with the file path, line number, and message. Add the code (like SA4006) so it's easy to look up in the staticcheck documentation (https://staticcheck.dev/docs/checks).
- Always report each finding with the file path, line number, and message. Add the code (like SA4006) so it's easy to look up in the [staticcheck documentation](https://staticcheck.dev/docs/checks).
- If you find issues in multiple files, group the findings by file.
- Tool-level errors (where file is empty and there's no code) are different from code-level findings—treat them separately. A tool error means your analysis might be incomplete.
- If you see `success: false`, figure out what went wrong (missing binary, module problems, timeout) before you try to report code issues.

---

## Proactive Fixes

For every finding, suggest a specific and minimal code fix.

- For every finding, suggest a specific and minimal code fix.
- Fix SA-family (correctness) findings first—they're more important than S1 or ST (style) findings.
- Don't call a Go code task done until checks returns no findings, or until you've acknowledged and justified any remaining ones.
- If you add new code to fix something, re-run checks on that file to make sure you didn't introduce new issues.
