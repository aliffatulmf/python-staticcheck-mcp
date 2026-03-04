# python-staticcheck-mcp

## Overview

A Model Context Protocol (MCP) server for automated Go code analysis and error explanation using staticcheck. This server exposes tools to run staticcheck checks and retrieve explanations for findings, making it easy to integrate Go static analysis into Python-based workflows, editors, or automation tools.

## Tools

1. `python_staticcheck_checks`
   - Runs staticcheck on Go files or directories.
   - Inputs:
     - `path` (string, absolute): Path to Go file or directory
     - `checks` (string or list, optional): Comma-separated or list of staticcheck checks to run
   - Returns: Formatted findings (severity, code, file, line, column, message)

2. `python_staticcheck_explain`
   - Provides official staticcheck explanation for a specific check code.
   - Inputs:
     - `code` (string): Staticcheck finding code (e.g., SA4006)
   - Returns: Explanation text for the finding

## Installation & Environment Setup

### Step 1: Install uv (No Python Required)

You can install uv using the recommended standalone installer or your package manager of choice. See the official [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/) for details.

#### Standalone installer (recommended)

macOS and Linux:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Or with wget:

```sh
wget -qO- https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell):

```sh
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

#### Package managers

- Homebrew (macOS):
  ```sh
  brew install uv
  ```
- WinGet (Windows):
  ```sh
  winget install --id=astral-sh.uv -e
  ```
- Scoop (Windows):
  ```sh
  scoop install main/uv
  ```
- PyPI (any platform):
  ```sh
  pip install uv
  ```

For more options, see the [uv documentation](https://docs.astral.sh/uv/getting-started/installation/).

### Step 2: Install as a uv Tool

Register the MCP server as a uv tool so it can be run globally:

```sh
uv tool install -e .
```

This will make `python-staticcheck-mcp` available as a uv tool.

### Step 3: Install Go and staticcheck

- Install Go from [golang.org](https://golang.org/dl/)
- Install staticcheck:

```sh
go install honnef.co/go/tools/cmd/staticcheck@latest
```

Make sure `staticcheck` is available in your PATH.

### Step 4: Build and Run the MCP Server with uv

To run the MCP server using uv:

```sh
uv tool run python-staticcheck-mcp
```

This will start the MCP server and make it available for MCP clients (such as VS Code, Zed, or other compatible tools).

## Usage with MCP (VS Code Example)

To use with MCP clients (example for VS Code), add the following to your `.vscode/mcp.json`:

```json
{
  "servers": {
    "python-staticcheck-mcp": {
      "command": "uv",
      "args": ["tool", "run", "python-staticcheck-mcp"]
    }
  }
}
```
