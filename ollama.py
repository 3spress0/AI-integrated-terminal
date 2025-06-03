#!/usr/bin/env python3
import subprocess
import sys
import re
import socket
import os
import json
import time
from colorama import init as colorama_init, Fore, Style
import requests

colorama_init(autoreset=True)

HISTORY_FILE = os.path.expanduser("~/.shell_history.json")
MODELS = ["codellama:latest"]  # Use Codellama latest tag

TEMPERATURE = 0.2
MAX_HISTORY_LENGTH = 2
RETRY_DELAY = 2  # seconds before exiting if model fails
OLLAMA_API_URL = "http://localhost:11434/api/chat"

SYSTEM_PROMPT = (
    "You are a sandboxed terminal assistant. "
    "Always think step-by-step, respond with a bash command in a code block, and finish with 'TASK COMPLETE'."
)

def load_history():
    try:
        history = json.load(open(HISTORY_FILE))
    except:
        history = []
    if not history or history[0].get("role") != "system":
        history.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    return history

def save_history(history):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(Fore.RED + f"[ERROR] Failed to save history: {e}")

def trim_history(history):
    base = [history[0]]
    filtered = [msg for msg in history[1:] if msg["role"] in ("user", "assistant")]
    return base + filtered[-(MAX_HISTORY_LENGTH * 2):]

def preprocess_cmd(cmd):
    # Replace hostnames with IPs to avoid DNS delays
    for host in set(re.findall(r"\b([A-Za-z0-9._-]+\.[A-Za-z]{2,})\b", cmd)):
        try:
            ip = socket.gethostbyname(host)
            cmd = cmd.replace(host, ip)
        except:
            pass
    return cmd

def execute_command_stream(cmd):
    if cmd.startswith("ping ") and "-c" not in cmd and "-n" not in cmd:
        cmd += " -c 4"
    cmd = preprocess_cmd(cmd)
    print(Fore.GREEN + f"💻 Executing Command: {cmd}\n")
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    for line in proc.stdout:
        print(Fore.WHITE + line, end="")
        lines.append(line)
    proc.wait()
    return "".join(lines).strip()

def call_ollama(messages, model_id):
    payload = {
        "model": model_id,
        "stream": False,
        "messages": messages
    }
    try:
        resp = requests.post(OLLAMA_API_URL, json=payload, timeout=60)
    except Exception as e:
        return None, f"network_error: {e}"

    if resp.status_code != 200:
        return None, f"error_{resp.status_code}: {resp.text}"

    try:
        data = resp.json()
    except Exception as e:
        return None, f"invalid_json: {e}"

    content = data.get("message", {}).get("content", "").strip()
    if not content:
        return None, "empty_response"
    return content, None

def chat_with_llm(message, history, model_id):
    history.append({"role": "user", "content": message})
    trimmed = trim_history(history)

    prompt_text = "\n".join(f"{m['role']}: {m['content']}" for m in trimmed)
    if len(prompt_text.split()) > 3800:
        # Drop oldest user/assistant pair if still too long
        trimmed = trimmed[:1] + trimmed[-(MAX_HISTORY_LENGTH * 2 - 1):]

    result, err = call_ollama(trimmed, model_id)
    if result:
        history.append({"role": "assistant", "content": result})
        save_history(history)
    return result, err

def extract_command(text):
    m = re.search(r"```bash\s*(.*?)\s*```", text, re.DOTALL)
    block = m.group(1) if m else text
    parts = [line.strip().lstrip("$").strip() for line in block.splitlines() if line.strip()]
    return " && ".join(parts)

def main():
    if len(sys.argv) < 2:
        print(Fore.RED + "Usage: python3 ollama_shell.py \"task description\"")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    print(Fore.BLUE + f"🎯 Task: {task}\n")

    chat_history = load_history()
    user_msg = task
    model_index = 0

    while True:
        if model_index >= len(MODELS):
            print(Fore.RED + "[ERROR] Codellama failed.")
            sys.exit(1)

        model_id = MODELS[model_index]
        print(Fore.CYAN + f"[INFO] Using model: {model_id}")

        llm_response, error = chat_with_llm(
            user_msg + "\nProvide next bash command in a code block.",
            chat_history,
            model_id
        )

        if error:
            print(Fore.YELLOW + f"[WARN] Model error: {error}. Exiting.\n")
            sys.exit(1)

        print(Fore.MAGENTA + "🧠 LLM Response:\n" + llm_response + "\n")
        cmd = extract_command(llm_response)
        out = execute_command_stream(cmd)
        user_msg = f"Command: {cmd}\nOutput:\n{out}"

        follow_up, error2 = chat_with_llm(
            user_msg + "\nProvide next bash command or 'TASK COMPLETE'.",
            chat_history,
            model_id
        )

        if error2:
            print(Fore.YELLOW + f"[WARN] Model error during follow-up: {error2}. Exiting.\n")
            sys.exit(1)

        print(Fore.MAGENTA + "🤖 Follow-Up:\n" + follow_up + "\n")
        if re.search(r"TASK COMPLETE", follow_up, re.IGNORECASE):
            print(Fore.GREEN + "✅ Task complete.")
            break

if __name__ == "__main__":
    main()
