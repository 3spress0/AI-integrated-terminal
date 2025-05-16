 #!/usr/bin/env python3
import subprocess
import requests
import sys
import re
import os

# ─── CONFIG ─────────────────────────────────────────────────────────────────
OLLAMA_MODEL = "deepseek-coder-v2:latest"
OLLAMA_API_URL = "http://localhost:11434/api/generate"
NOTES_FILE = 'notepad.txt'
MAX_EMPTY_RETRIES = 3

# Ensure notes file exists
if not os.path.exists(NOTES_FILE):
    open(NOTES_FILE, 'w').close()

# System prompt: enforce clear instructions and prohibit placeholders
system_prompt = (
    "You are a terminal assistant running inside a secure sandbox environment. "
    "You have sudo privileges and full session memory. "
    "Your goal is to find a valid vulnerability on the target system.\n"
    "GUIDELINES (MUST FOLLOW EXACTLY):\n"
    "1. Always output exactly ONE bash command per response inside a markdown code block labeled 'bash'.\n"
    "2. Do NOT use ANY placeholders (e.g., <IP_ADDRESS>, <URL>, <FILENAME>). Use actual values discovered or the original target.\n"
    "3. After executing each command, analyze the output and write any important findings as notes prefixed with 'NOTE:'.\n"
    "4. Then propose the next tool or command to use in the same strict format.\n"
    "5. Repeat until you confirm a specific vulnerability. Only then respond with 'TASK COMPLETE' in a bash code block.\n"
    "6. Do not include any plain text commands outside the code block or any extra markdown."
)
chat_history = [{"role": "system", "content": system_prompt}]

# Execute command with live output
def execute_command_stream(cmd: str, timeout: int = None) -> str:
    print(f"💻 Executing Command (live output): {cmd}\n")
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output_lines = []
    try:
        for line in proc.stdout:
            print(line, end='')
            output_lines.append(line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        output_lines.append("\nCommand timed out.\n")
    return ''.join(output_lines).strip()

# Chat with LLM via Ollama
def chat_with_llm(message: str) -> str:
    chat_history.append({"role": "user", "content": message})
    prompt = "".join(f"{m['role']}: {m['content']}\n" for m in chat_history)
    resp = requests.post(
        OLLAMA_API_URL,
        json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False, "temperature": 0.3},
        timeout=120
    )
    data = resp.json()
    text = data.get("response") or data.get("choices", [{}])[0].get("text", "")
    reply = text.strip()
    chat_history.append({"role": "assistant", "content": reply})
    return reply

# Extract bash command from LLM output
def extract_command(text: str) -> str:
    m = re.search(r"```bash\s*(.*?)\s*```", text, re.DOTALL)
    block = m.group(1) if m else text
    lines = []
    for line in block.splitlines():
        stripped = line.strip().lstrip('$').strip()
        if not stripped or stripped.startswith('#') or stripped.upper().startswith('NOTE:'):
            continue
        lines.append(stripped)
    return ' && '.join(lines)

# Save notes
def parse_and_store_notes(text: str):
    for line in text.splitlines():
        if line.strip().upper().startswith('NOTE:'):
            with open(NOTES_FILE, 'a') as f:
                f.write(line.strip() + '\n')

# Main workflow: handle failures and loop
COMMAND_FAILURE_PATTERNS = [r"command not found", r"not found"]

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 deepseek_shell.py \"task description\"")
        sys.exit(1)
    task = " ".join(sys.argv[1:])
    print(f"🎯 Task: {task}\n")
    user_msg = f"Task: {task}"
    empty_retries = 0

    while True:
        # Request next command
        llm_out = chat_with_llm(user_msg + "\nProvide the next bash command in a markdown code block labeled 'bash'.")
        print("🧠 LLM Response:\n", llm_out, "\n")
        parse_and_store_notes(llm_out)

        cmd = extract_command(llm_out)
        if not cmd:
            empty_retries += 1
            if empty_retries >= MAX_EMPTY_RETRIES:
                error_msg = "ERROR: You must output exactly one bash command inside a 'bash' code block with no placeholders."
                user_msg = error_msg
                empty_retries = 0
                continue
            else:
                # keep same user_msg to retry
                continue

        empty_retries = 0
        output = execute_command_stream(cmd)
        print(f"\n📤 Collected Output:\n{output}\n")

        # Handle command failure by setting context for next prompt
        if any(re.search(pat, output, re.IGNORECASE) for pat in COMMAND_FAILURE_PATTERNS):
            error_msg = f"WARNING: The last command failed with error:\n{output}\nPropose an alternative valid command without placeholders in a bash code block."
            user_msg = error_msg
            continue

        # Check completion
        if re.search(r"TASK COMPLETE", llm_out, re.IGNORECASE):
            print(f"✅ Task complete. Check {NOTES_FILE} for notes. Exiting.")
            break

        # Generate next context
        user_msg = f"Command: {cmd}\nOutput:\n{output}"

if __name__ == "__main__":
    main()

