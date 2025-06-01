#!/usr/bin/env python3
import subprocess
import sys
import re
import socket
import os
import json
import time
import requests
from colorama import init as colorama_init, Fore, Style

colorama_init(autoreset=True)

HISTORY_FILE = os.path.expanduser("~/.shell_history.json")
PHIND_API_KEY = "[redacted]"
MODEL_NAME = "Phind-CodeLlama-34B-v2"
TEMPERATURE = 0.2
MAX_TOKENS = 500
MAX_HISTORY_LENGTH = 10
MAX_RETRIES = 3
RETRY_DELAY = 60

SYSTEM_PROMPT = (
    "You are a terminal assistant running inside a secure sandbox environment. "
    "You have full sudo privileges and are allowed to install packages. "
    "Maintain memory up to recent messages. ALWAYS THINK step-by-step and output a bash command in a code block with sudo as needed. "
    "After executing, review output and propose next command. Stop when you state 'TASK COMPLETE'."
)

def load_history():
    try:
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = []
    if not history or history[0].get('role') != 'system':
        history.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    return history

chat_history = load_history()

def trim_history(history):
    base = [history[0]]
    return base + history[-MAX_HISTORY_LENGTH:]

def preprocess_cmd(cmd):
    for host in set(re.findall(r"\b([A-Za-z0-9._-]+\.[A-Za-z]{2,})\b", cmd)):
        try:
            ip = socket.gethostbyname(host)
            cmd = cmd.replace(host, ip)
        except:
            pass
    return cmd

def execute_command_stream(cmd):
    if cmd.startswith('ping ') and '-c' not in cmd and '-n' not in cmd:
        cmd += ' -c 4'
    cmd = preprocess_cmd(cmd)
    print(Fore.GREEN + f"💻 Executing Command: {cmd}\n")
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    for line in proc.stdout:
        print(Fore.WHITE + line, end='')
        lines.append(line)
    proc.wait()
    return ''.join(lines).strip()

def save_history(history):
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(Fore.RED + f"[ERROR] Failed to save history: {e}")

def chat_with_phind(messages):
    url = "https://api.phind.com/agent/"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {PHIND_API_KEY}",
    }
    payload = {
        "messages": messages,
        "model": MODEL_NAME,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            reply = response.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return reply
        except requests.exceptions.RequestException as e:
            print(Fore.RED + f"[ERROR] Phind API error: {e}")
            break
    return "TASK COMPLETE"

def extract_command(text):
    m = re.search(r"```bash\s*(.*?)\s*```", text, re.DOTALL)
    block = m.group(1) if m else text
    parts = [l.strip().lstrip('$').strip() for l in block.splitlines() if l.strip()]
    return ' && '.join(parts)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(Fore.RED + "Usage: python3 Ai.py \"task description\"")
        sys.exit(1)
    task = " ".join(sys.argv[1:])
    print(Fore.BLUE + f"🎯 Task: {task}\n")
    user_msg = task
    while True:
        llm = chat_with_phind([{"role": "user", "content": user_msg + "\nProvide next bash command in a code block."}])
        print(Fore.MAGENTA + "🧠 LLM Response:\n" + llm + "\n")
        cmd = extract_command(llm)
        out = execute_command_stream(cmd)
        user_msg = f"Command: {cmd}\nOutput:\n{out}"
        follow = chat_with_phind([{"role": "user", "content": user_msg + "\nProvide next bash command or 'TASK COMPLETE'."}])
        print(Fore.MAGENTA + "🤖 Follow-Up:\n" + follow + "\n")
        if re.search(r"TASK COMPLETE", follow, re.IGNORECASE):
            print(Fore.GREEN + "✅ Task complete.")
            break
