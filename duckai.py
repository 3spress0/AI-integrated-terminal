#!/usr/bin/env python3
#code will probably not work.
#still early beta
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
MODEL_ID = 1  # default GPT-4o-mini on Duck.ai
MAX_HISTORY_LENGTH = 10
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

system_prompt = (
    "You are a terminal assistant running inside a secure sandbox environment. "
    "You have full sudo privileges and are allowed to install packages. "
    "Maintain memory up to recent messages. ALWAYS THINK step-by-step and output a bash command in a code block with sudo as needed. "
    "After executing, review output and propose next command. Stop when you state 'TASK COMPLETE'."
)

# Load or initialize conversation history
def load_history():
    try:
        history = json.load(open(HISTORY_FILE))
    except FileNotFoundError:
        history = []
    if not history or history[0].get('role') != 'system':
        history.insert(0, {"role": "system", "content": system_prompt})
    return history

chat_history = load_history()

# Save history to file
def save_history(history):
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(Fore.RED + f"[ERROR] Failed to save history: {e}")

# Keep only recent messages plus system prompt
def trim_history(history):
    return [history[0]] + history[-MAX_HISTORY_LENGTH:]

# Replace hostnames with IPs in commands
def preprocess_cmd(cmd):
    for host in set(re.findall(r"\b([A-Za-z0-9._-]+\.[A-Za-z]{2,})\b", cmd)):
        try:
            ip = socket.gethostbyname(host)
            cmd = cmd.replace(host, ip)
        except Exception:
            pass
    return cmd

# Execute and stream the shell command
def execute_command_stream(cmd):
    if cmd.startswith('ping ') and '-c' not in cmd and '-n' not in cmd:
        cmd += ' -c 4'
    cmd = preprocess_cmd(cmd)
    print(Fore.GREEN + f"💻 Executing Command: {cmd}\n")
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output = []
    for line in proc.stdout:
        print(Fore.WHITE + line, end='')
        output.append(line)
    proc.wait()
    return ''.join(output).strip()

# Send a message to Duck.ai and get response via duckchat module
def chat_with_llm(query):
    chat_history.append({"role": "user", "content": query})
    save_history(chat_history)

    simple_query = query.replace("\n", " ")
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            cmd = [
                sys.executable, "-m", "duckchat",
                "-y",
                "-m", str(MODEL_ID),
                "-q", simple_query
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            reply = result.stdout.strip()
            if not reply:
                print(Fore.YELLOW + f"[WARN] Empty response, retrying ({attempt}/{MAX_RETRIES})")
                time.sleep(RETRY_DELAY)
                continue
            chat_history.append({"role": "assistant", "content": reply})
            save_history(chat_history)
            return reply
        except subprocess.TimeoutExpired:
            print(Fore.RED + f"[ERROR] Request timed out (attempt {attempt})")
        except Exception as e:
            print(Fore.RED + f"[ERROR] {e}")
        time.sleep(RETRY_DELAY)

    print(Fore.CYAN + "[INFO] All retries failed. TASK COMPLETE.")
    return "TASK COMPLETE"

# Extract the bash command from LLM response
def extract_command(text):
    match = re.search(r"```bash\s*(.*?)\s*```", text, re.DOTALL)
    block = match.group(1) if match else text
    lines = [l.strip().lstrip('$') for l in block.splitlines() if l.strip()]
    return ' && '.join(lines)

# Main execution loop
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(Fore.RED + "Usage: python3 duckai.py \"task description\"")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    print(Fore.BLUE + f"🎯 Task: {task}\n")
    user_msg = task

    while True:
        llm_response = chat_with_llm(user_msg + " Provide next bash command in a code block.")
        print(Fore.MAGENTA + f"🧠 LLM Response:\n{llm_response}\n")

        cmd = extract_command(llm_response)
        if not cmd:
            print(Fore.RED + "[ERROR] No command extracted. TASK COMPLETE.")
            break

        out = execute_command_stream(cmd)
        user_msg = f"Command: {cmd} Output: {out}"

        follow = chat_with_llm(user_msg + " Provide next bash command or 'TASK COMPLETE'.")
        print(Fore.MAGENTA + f"🤖 Follow-Up:\n{follow}\n")

        if re.search(r"TASK COMPLETE", follow, re.IGNORECASE):
            print(Fore.GREEN + "✅ Task complete.")
            break
