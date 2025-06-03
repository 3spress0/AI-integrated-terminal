#!/usr/bin/env python3
import subprocess
import sys
import re
import socket
import os
import json
import time
from colorama import init as colorama_init, Fore, Style

colorama_init(autoreset=True)

HISTORY_FILE = os.path.expanduser("~/.shell_history.json")
MODELS = ["codellama", "phi3", "llama3"]  # Local models via Ollama

TEMPERATURE = 0.2
MAX_HISTORY_LENGTH = 5
RETRY_DELAY = 2  # seconds to wait before switching to next model

SYSTEM_PROMPT = (
    "You are a terminal assistant running inside a secure sandbox environment. "
    "You have full sudo privileges and are allowed to install packages. "
    "Maintain memory up to recent messages. ALWAYS THINK step-by-step and output a bash command in a code block with sudo as needed. "
    "After executing, review output and propose next command. Stop when you state 'TASK COMPLETE'."
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
    # Keep system prompt + last MAX_HISTORY_LENGTH user/assistant pairs
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
    # If it's a ping without -c or -n, add "-c 4"
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
    # Build a single prompt string from the chat history
    prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    try:
        result = subprocess.run(
            ["ollama", "run", model_id],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=120
        )
        return result.stdout.strip(), None
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except Exception as e:
        return None, f"error: {e}"

def chat_with_llm(message, history, model_id):
    history.append({"role": "user", "content": message})
    trimmed = trim_history(history)
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
            print(Fore.RED + "[ERROR] All local models failed.")
            sys.exit(1)

        model_id = MODELS[model_index]
        print(Fore.CYAN + f"[INFO] Trying model: {model_id}")

        # 1) Ask for next bash command
        llm_response, error = chat_with_llm(
            user_msg + "\nProvide next bash command in a code block.",
            chat_history,
            model_id
        )

        if error:
            print(Fore.YELLOW + f"[WARN] Model error: {error}. Trying next model...\n")
            model_index += 1
            time.sleep(RETRY_DELAY)
            continue

        print(Fore.MAGENTA + "🧠 LLM Response:\n" + llm_response + "\n")
        cmd = extract_command(llm_response)
        out = execute_command_stream(cmd)
        user_msg = f"Command: {cmd}\nOutput:\n{out}"

        # 2) Ask for follow‑up (next command or TASK COMPLETE)
        follow_up, error2 = chat_with_llm(
            user_msg + "\nProvide next bash command or 'TASK COMPLETE'.",
            chat_history,
            model_id
        )

        if error2:
            print(Fore.YELLOW + f"[WARN] Model error during follow-up: {error2}. Trying next model...\n")
            model_index += 1
            time.sleep(RETRY_DELAY)
            continue

        print(Fore.MAGENTA + "🤖 Follow-Up:\n" + follow_up + "\n")
        if re.search(r"TASK COMPLETE", follow_up, re.IGNORECASE):
            print(Fore.GREEN + "✅ Task complete.")
            break

if __name__ == "__main__":
    main()
