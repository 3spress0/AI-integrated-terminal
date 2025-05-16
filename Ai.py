#!/usr/bin/env python3
import subprocess
import sys
import re
import socket
import os
import json
from openai import OpenAI

# ─── CONFIG VARIABLES ─────────────────────────────────────────────────────────
HISTORY_FILE       = os.path.expanduser("~/.deepseek_shell_history.json")  # Path for chat history
# Your OpenAI API key (inserted directly)
OPENAI_API_KEY     = "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"
MODEL_NAME         = "gpt-4o-mini"                                          # ChatCompletion model
TEMPERATURE        = 0.2                                                      # Sampling temperature
MAX_TOKENS         = 500                                                      # Max tokens per response
MAX_HISTORY_LENGTH = 10                                                       # Max messages to keep in history

# Instantiate OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# ─── SYSTEM PROMPT ─────────────────────────────────────────────────────────────
system_prompt = (
    "You are a terminal assistant running inside a secure sandbox environment. "
    "You have full sudo privileges and are explicitly allowed to install packages and make system changes using sudo as needed. "
    "Maintain full memory of the session (up to recent messages). ALWAYS THINK step-by-step and immediately output a bash command in a code block, prefixing install commands with sudo. "
    "After executing, review the output and then propose the next command. Stop only when you state 'TASK COMPLETE'."
    "You are in a minimal ubuntu env. so you may need to install some tools before you start."
    "When installing tools, add the -y at the end to make sure it doesnt stall."
)

# ─── HISTORY MANAGEMENT ─────────────────────────────────────────────────────────

def load_history():
    try:
        return json.load(open(HISTORY_FILE))
    except:
        return [{"role": "system", "content": system_prompt}]


def save_history(history):
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"⚠️ Warning: Could not save history: {e}")

chat_history = load_history()

# Trim history to last N messages

def trim_history(history):
    # Always keep system prompt at index 0
    base = [history[0]]
    recent = history[-MAX_HISTORY_LENGTH:]
    return base + recent

# ─── HELPER FUNCTIONS ────────────────────────────────────────────────────────────

def preprocess_cmd(cmd):
    """Resolve hostnames inline to avoid DNS delays."""
    for host in set(re.findall(r"\b([A-Za-z0-9._-]+\.[A-Za-z]{2,})\b", cmd)):
        try:
            ip = socket.gethostbyname(host)
            cmd = cmd.replace(host, ip)
        except:
            pass
    return cmd


def execute_command_stream(cmd):
    """Run a bash command with live updating output."""
    cmd = preprocess_cmd(cmd)
    print(f"💻 Executing Command: {cmd}\n")
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output_lines = []
    for line in proc.stdout:
        print(line, end='')
        output_lines.append(line)
    proc.wait()
    return ''.join(output_lines).strip()


def chat_with_llm(message):
    """Send a message to OpenAI, trimming history if needed."""
    chat_history.append({"role": "user", "content": message})
    # Trim before API call
    trimmed = trim_history(chat_history)
    save_history(chat_history)

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=trimmed,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS
    )

    reply = response.choices[0].message.content.strip()
    chat_history.append({"role": "assistant", "content": reply})
    save_history(chat_history)
    return reply


def extract_command(text):
    """Parse the first bash code block into a single shell command."""
    m = re.search(r"```bash\s*(.*?)\s*```", text, re.DOTALL)
    block = m.group(1) if m else text
    lines = [l.strip().lstrip('$').strip() for l in block.splitlines() if l.strip() and not l.strip().startswith('#')]
    return ' && '.join(lines)

# ─── MAIN LOOP ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 Ai.py \"task description\"")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    print(f"🎯 Task: {task}\n")
    user_msg = task

    while True:
        llm_response = chat_with_llm(user_msg + "\nProvide the next bash command in a code block.")
        print("🧠 LLM Response:\n", llm_response, "\n")

        cmd = extract_command(llm_response)
        output = execute_command_stream(cmd)
        user_msg = f"Command: {cmd}\nOutput:\n{output}"

        follow = chat_with_llm(user_msg + "\nProvide next bash command or 'TASK COMPLETE'.")
        print("🤖 Follow-Up:\n", follow, "\n")

        if re.search(r"TASK COMPLETE", follow, re.IGNORECASE):
            print("✅ Task complete.")
            break
