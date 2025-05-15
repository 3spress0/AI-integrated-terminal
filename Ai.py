#!/usr/bin/env python3
import subprocess
import requests
import sys
import re
import socket

# ─── CONFIG ─────────────────────────────────────────────────────────────────
FREE_GPT_API_URL = "https://free-unoficial-gpt4o-mini-api-g70n.onrender.com/chat/?query="

# System prompt: full memory, sandbox context, must always output commands
system_prompt = (
    "You are a terminal assistant running inside a secure sandbox environment. "
    "You have sudo privileges. All commands run in an isolated session; outputs are captured and fed back. "
    "Maintain full memory of the session. ALWAYS THINK step-by-step and immediately output a bash command in a code block. "
    "After executing, review the output and then propose the next command. Stop only when you state 'TASK COMPLETE'. "
    "Always verify if you've done your job correctly. If you do not send a bash command, the script will continue in a loop for eternity."
)

# Conversation history
chat_history = [{"role": "system", "content": system_prompt}]

# Preprocess: resolve hostnames to IPs for versatile commands
def preprocess_cmd(cmd: str) -> str:
    for host in set(re.findall(r"\b([a-zA-Z0-9._-]+\.[a-zA-Z]{2,})\b", cmd)):
        try:
            ip = socket.gethostbyname(host)
            cmd = re.sub(rf"\b{re.escape(host)}\b", ip, cmd)
        except Exception:
            pass
    return cmd

# Execute command with live streaming output
def execute_command_stream(cmd: str) -> str:
    cmd = preprocess_cmd(cmd)
    print(f"💻 Executing Command (live output): {cmd}\n")
    process = subprocess.Popen(['bash', '-c', cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output_lines = []
    for line in process.stdout:
        print(line, end='')
        output_lines.append(line)
    process.wait()
    return ''.join(output_lines).strip()

# Chat with LLM via Free GPT API, retaining full history
def chat_with_llm(message: str) -> str:
    chat_history.append({"role": "user", "content": message})
    prompt = "\n".join(f"{m['role']}: {m['content']}" for m in chat_history)
    try:
        response = requests.get(FREE_GPT_API_URL + requests.utils.quote(prompt), timeout=120)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"❌ ERROR: Failed to communicate with Free GPT API: {e}")
        sys.exit(1)

    data = response.json()
    reply = data.get("response", "").strip()
    chat_history.append({"role": "assistant", "content": reply})
    return reply

# Extract and prepare command from LLM output
def extract_command(text: str) -> str:
    m = re.search(r"```bash\s*(.*?)\s*```", text, re.DOTALL)
    block = m.group(1) if m else text
    lines = []
    for line in block.splitlines():
        line = line.strip().lstrip('$').strip()
        if not line or line.startswith('#'):
            continue
        lines.append(line)
    return ' && '.join(lines)

# Main workflow
def main():
    if len(sys.argv) < 2:
        print("Usage: sudo python3 deepseek_shell.py \"task description\"")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    print(f"🎯 Task: {task}\n")

    user_msg = f"{task}"
    while True:
        llm_out = chat_with_llm(user_msg + "\nProvide the next bash command in a code block.")
        print("🧠 LLM Command:\n", llm_out, "\n")

        cmd = extract_command(llm_out)
        output = execute_command_stream(cmd)
        print(f"\n📤 Collected Output:\n{output}\n")

        user_msg = f"Command: {cmd}\nOutput:\n{output}"
        follow_up = chat_with_llm(user_msg + "\nProvide next bash command or 'TASK COMPLETE'.")
        print("🤖 Follow-Up:\n", follow_up, "\n")

        if re.search(r"TASK COMPLETE", follow_up, re.IGNORECASE):
            print("✅ Task complete. Exiting.")
            break

if __name__ == "__main__":
    main()