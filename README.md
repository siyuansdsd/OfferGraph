# OfferGraph

<p align="center">
  <img src="./assets/logo.png" alt="OfferGraph logo" width="720">
</p>

An Offer hunter ai agent team based on LangGraph, allowed monitor and future customize, and have manus agent error memory feat, to give users a free, efficient, cheap way to get easy offer.

## Setup

```bash
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Fill `.env` with local secrets:

```bash
TAVILY_API_KEY=...
MINIMAX_API_KEY=...
```

## Agent Console

Run the LinkedIn agent from a local console and choose `MiniMax-M2.7` or `MiniMax-M2.5`:

```bash
./.venv/bin/python scripts/agent_console.py --agent linkedin-master
```

Non-interactive example:

```bash
./.venv/bin/python scripts/agent_console.py \
  --agent linkedin-master \
  --model MiniMax-M2.7 \
  --message "Write a concise OfferGraph LinkedIn post."
```

## Tool Approval Mode

Tools default to `approve-mode`, which returns an approval request before running flows that need user consent.

```bash
export OFFERGRAPH_TOOL_MODE=approve-mode
```

Use `auto-mode` only when you want tools to skip approval gates:

```bash
export OFFERGRAPH_TOOL_MODE=auto-mode
```

To initialize LinkedIn auth state manually:

```bash
./.venv/bin/python -m playwright install chromium
./.venv/bin/python scripts/setup_linkedin_auth.py
```
