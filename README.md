# 🦘 Quokka Agent

A local lightweight agent for PC automation with remote control via Telegram.

## Features

- **🤖 Multi-LLM Support**: Uses local Ollama for fast operations, with OpenRouter fallback for complex tasks
- **📱 Telegram Interface**: Control your PC remotely via Telegram bot
- **🔒 Security Layer**: Command allowlist, directory restrictions, and audit logging
- **🧰 Built-in Tools**: Shell execution, file operations, PDF handling, Obsidian integration
- **🖼️ Multimodal**: OCR for images, PDF text extraction
- **💾 Persistent Memory**: Session history and async task queue
- **🚀 Systemd Service**: Runs as a background service with auto-start on boot

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Telegram Bot  │────▶│  Prompt Manager  │────▶│   LLM Router    │
│  (Transport)    │     │  (Context Prep)  │     │ (Ollama/Cloud) │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                         │
                                                         ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Tool Executor  │◀────│     Planner      │◀────│   LLM Response  │
│  (Sandboxed)    │     │ (Plan Formulator)│     │   (Tool Calls)  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Tool Registry                             │
│  shell_exec | file_ops | pdf_handler | web_fetch | obsidian    │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Security Layer                              │
│  Allowlist Checker | Directory Jail | Dry-run Mode | Audit Log │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites

- **Python 3.10+**
- **systemd** (for service installation)
- **[Ollama](https://ollama.ai)** (recommended for local LLM)
- **Tesseract OCR** (optional, for image processing)
- **Telegram Bot Token** (from [@BotFather](https://t.me/BotFather))

### Method 1: Automated Installation (Recommended)

The easiest way to install Quokka Agent as a systemd service:

```bash
# 1. Download and extract
unzip quokka-agent.zip
cd quokka-agent

# 2. Make scripts executable
chmod +x install.sh uninstall.sh

# 3. Run installer
sudo ./install.sh
```

The installer will:
- ✅ Check all prerequisites
- ✅ Create a dedicated service user (`quokka`)
- ✅ Install to `/opt/quokka-agent`
- ✅ Create virtual environment and install dependencies
- ✅ Set up configuration files in `/etc/quokka/`
- ✅ Create and enable systemd service
- ✅ Optionally start the service immediately

### Method 2: Manual Installation

For development or custom setups:

```bash
# 1. Clone or extract the agent
cd agent-python

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install
pip install -e .

# 4. Configure
cp config/config.yaml ~/.config/quokka/
# Edit the config file and add your Telegram token

# 5. Run
python -m quokka
```

### Method 3: Using pip (Coming Soon)

```bash
pip install quokka-agent
quokka init --telegram-token YOUR_TOKEN
quokka run
```

## Post-Installation Setup

### 1. Configure Telegram Bot Token

**Option A: Edit config file**
```bash
sudo nano /etc/quokka/config.yaml
```
Add your token in the `telegram.token` field.

**Option B: Use environment file**
```bash
sudo nano /etc/quokka/environment
```
Uncomment and set `QUOKKA_TELEGRAM__TOKEN=your_token_here`

### 2. Set Up Ollama (Local LLM)

```bash
# Install Ollama (if not already installed)
curl -fsSL https://ollama.ai/install.sh | sh

# Download a model
ollama pull llama3.1:8b

# Start Ollama (usually auto-starts)
ollama serve
```

### 3. (Optional) Configure OpenRouter for Cloud Fallback

```bash
sudo nano /etc/quokka/environment
```
Set `QUOKKA_OPENROUTER__API_KEY=your_key_here`

Get your API key from [OpenRouter](https://openrouter.ai).

## Service Management

### Systemd Commands

| Action | Command |
|--------|---------|
| Start | `sudo systemctl start quokka-agent` |
| Stop | `sudo systemctl stop quokka-agent` |
| Restart | `sudo systemctl restart quokka-agent` |
| Status | `sudo systemctl status quokka-agent` |
| Enable auto-start | `sudo systemctl enable quokka-agent` |
| Disable auto-start | `sudo systemctl disable quokka-agent` |

### Viewing Logs

```bash
# Follow logs in real-time
sudo journalctl -u quokka-agent -f

# View recent logs
sudo journalctl -u quokka-agent -n 100

# View logs from today
sudo journalctl -u quokka-agent --since today

# View logs from specific time
sudo journalctl -u quokka-agent --since "2024-01-01 10:00:00"
```

Log files are also stored at:
- Agent logs: `/var/log/quokka/agent.log`
- Audit logs: `/var/lib/quokka/logs/audit/`

## Configuration

Configuration is stored in `/etc/quokka/config.yaml`. You can also use environment variables:

```bash
export QUOKKA_TELEGRAM__TOKEN="your_token"
export QUOKKA_OLLAMA__MODEL="llama3.1:8b"
export QUOKKA_OPENROUTER__API_KEY="your_key"
```

### Key Settings

| Setting | Description | Default |
|---------|-------------|---------|
| `telegram.token` | Bot token from @BotFather | *(required)* |
| `telegram.allowed_users` | Whitelist of Telegram user IDs | `[]` (all) |
| `telegram.admin_users` | Admin users (bypass restrictions) | `[]` |
| `ollama.model` | Local LLM model name | `llama3.1:8b` |
| `openrouter.api_key` | Cloud LLM API key | *(optional)* |
| `security.allowed_commands` | Commands that can be executed | See config |
| `security.allowed_directories` | Accessible directories | `["~"]` |

### Finding Your Telegram User ID

1. Start a chat with [@userinfobot](https://t.me/userinfobot) on Telegram
2. It will reply with your user ID
3. Add this ID to `allowed_users` or `admin_users` in the config

## Available Tools

### `shell_exec`
Execute shell commands with security restrictions.

```
User: "List all Python files in my projects folder"
Agent: Uses shell_exec with: find ~/projects -name "*.py"
```

### `file_ops`
Read, write, list, and manage files.

```
User: "Read my notes.txt file"
Agent: Uses file_ops with: operation=read, path=notes.txt
```

### `obsidian_read` / `obsidian_write`
Search and manage Obsidian notes.

```
User: "Find all notes tagged with #project"
Agent: Uses obsidian_read with: operation=tags, tag=#project
```

Set your vault path: `export OBSIDIAN_VAULT=/path/to/vault`

### `pdf_handler`
Extract text from PDF files.

```
User: [Sends PDF file]
Agent: Uses pdf_handler to extract and summarize content
```

### `web_fetch`
Make HTTP requests.

```
User: "What's on hacker news front page?"
Agent: Uses web_fetch to get and summarize content
```

## Security Features

### 1. Command Allowlist
Only whitelisted commands can be executed. Default allowed:
```
ls, cat, head, tail, grep, find, pwd, echo, git, python, pip, npm, node, bun, code, nvim, mkdir, touch, cp, mv, rm, chmod
```

### 2. Command Blocklist
Dangerous commands are always blocked:
```
sudo, su, passwd, chmod 777, dd, mkfs
```

### 3. Directory Jail
File operations restricted to allowed directories (default: home directory).

### 4. Dry-Run Mode
Preview actions before execution. Toggle with `/dryrun` command in Telegram.

### 5. Audit Logging
All actions are logged to `/var/lib/quokka/logs/audit/` for review.

### 6. User Whitelist
Only authorized Telegram users can interact with the bot.

### Admin Mode

Users in `admin_users` bypass:
- Command allowlist (but not blocklist)
- Directory restrictions
- Some confirmation prompts

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot and see welcome message |
| `/help` | Show detailed help |
| `/status` | Show current session status |
| `/dryrun` | Toggle dry-run mode (preview actions) |
| `/clear` | Clear conversation history |
| `/cancel` | Cancel current operation |

## Usage Examples

### Basic Chat
```
User: Hello!
Agent: Hi! I'm Quokka, your local automation assistant. How can I help you today?
```

### File Operations
```
User: Create a new file called todo.md in my Documents folder
Agent: I'll create that file for you.
[Creates file with initial content]
```

### Shell Commands
```
User: Check disk usage on my system
Agent: [Uses df -h command]
Here's your disk usage:
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda1       256G  180G   76G  71% /
...
```

### Obsidian Integration
```
User: Search my vault for notes about "machine learning"
Agent: [Searches Obsidian vault]
Found 5 notes matching "machine learning":
1. ML Basics.md
2. Neural Networks.md
...
```

## File Locations

| File/Folder | Location |
|-------------|----------|
| Installation | `/opt/quokka-agent/` |
| Configuration | `/etc/quokka/config.yaml` |
| Environment | `/etc/quokka/environment` |
| Session Data | `/var/lib/quokka/sessions/` |
| Task Queue | `/var/lib/quokka/tasks/` |
| Logs | `/var/log/quokka/` |
| Audit Logs | `/var/lib/quokka/logs/audit/` |

## Uninstallation

```bash
# Run the uninstaller
sudo ./uninstall.sh

# Or manually:
sudo systemctl stop quokka-agent
sudo systemctl disable quokka-agent
sudo rm /etc/systemd/system/quokka-agent.service
sudo systemctl daemon-reload
sudo rm -rf /opt/quokka-agent
sudo rm -rf /etc/quokka
sudo rm -rf /var/lib/quokka
sudo rm -rf /var/log/quokka
sudo userdel quokka
```

## Troubleshooting

### Service won't start

```bash
# Check service status
sudo systemctl status quokka-agent

# Check logs
sudo journalctl -u quokka-agent -n 50

# Check if config is valid
cat /etc/quokka/config.yaml
```

### Ollama not responding

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama
ollama serve

# Check if model is downloaded
ollama list
```

### Telegram bot not working

1. Check your bot token is correct in `/etc/quokka/config.yaml`
2. Make sure you've started a chat with your bot
3. Verify your user ID is in `allowed_users` (or leave empty to allow all)
4. Check logs: `sudo journalctl -u quokka-agent -f`

### Commands being blocked

Check the security configuration:
- `allowed_commands` in `/etc/quokka/config.yaml`
- `allowed_directories` in `/etc/quokka/config.yaml`
- Audit logs in `/var/lib/quokka/logs/audit/`

### Permission errors

```bash
# Fix permissions
sudo chown -R quokka:quokka /var/lib/quokka
sudo chown -R quokka:quokka /var/log/quokka
sudo chmod 750 /etc/quokka
sudo chmod 640 /etc/quokka/config.yaml
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black quokka/

# Type check
mypy quokka/
```

## Project Structure

```
quokka/
├── __init__.py          # Package init
├── __main__.py          # Entry point
├── agent.py             # Main agent class
├── cli.py               # CLI commands
├── core/
│   ├── config.py        # Configuration management
│   ├── logger.py        # Logging setup
│   └── types.py         # Data models
├── transport/
│   └── telegram.py      # Telegram bot
├── llm/
│   ├── base.py          # LLM interface
│   ├── ollama_client.py # Ollama integration
│   ├── openrouter_client.py  # OpenRouter integration
│   └── router.py        # LLM routing logic
├── security/
│   └── security.py      # Security layer
├── tools/
│   ├── base.py          # Tool interface
│   ├── shell_exec.py    # Shell execution
│   ├── file_ops.py      # File operations
│   ├── pdf_handler.py   # PDF processing
│   ├── web_fetch.py     # HTTP requests
│   └── obsidian.py      # Obsidian integration
├── planner/
│   └── planner.py       # Plan formulation
├── executor/
│   └── executor.py      # Tool execution
├── memory/
│   ├── session.py       # Session management
│   └── task_queue.py    # Async task queue
└── multimodal/
    └── handler.py       # Multimodal processing
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `QUOKKA_CONFIG` | Path to config file |
| `QUOKKA_TELEGRAM__TOKEN` | Telegram bot token |
| `QUOKKA_TELEGRAM__ALLOWED_USERS` | Allowed user IDs |
| `QUOKKA_OLLAMA__MODEL` | Ollama model name |
| `QUOKKA_OPENROUTER__API_KEY` | OpenRouter API key |
| `OBSIDIAN_VAULT` | Path to Obsidian vault |

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

- **Issues**: Open an issue on GitHub
- **Telegram**: Join our community (coming soon)
