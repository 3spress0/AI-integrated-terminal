#!/usr/bin/env python3
import subprocess
import requests
import sys
import re
import os
import json
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

# ─── CONFIG ─────────────────────────────────────────────────────────────────
OLLAMA_MODEL    = "deepseek-coder-v2:latest"
OLLAMA_API_URL  = "http://localhost:11434/api/generate"
NOTES_FILE      = 'notepad.txt'
SESSION_FILE    = 'session.json'
MAX_EMPTY_RETRIES = 3

# Ensure notes file exists
if not os.path.exists(NOTES_FILE):
    open(NOTES_FILE, 'w').close()

# ─── SYSTEM PROMPT & CHAT HISTORY ─────────────────────────────────────────────
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
    "6. If you need tool documentation, respond with TOOL_PAGE: <toolname>.\n"
    "7. If you need general info, use WEB_SEARCH: <query>.\n"
    "8. Do not include any plain text commands outside the code block or any extra markdown."
)

# If session.json exists, load it; otherwise, start fresh with only the system prompt
if os.path.exists(SESSION_FILE):
    with open(SESSION_FILE, 'r') as f:
        data = json.load(f)
        chat_history = data.get('chat_history',
                                [{"role": "system", "content": system_prompt}])
else:
    chat_history = [{"role": "system", "content": system_prompt}]

# ─── COMMAND EXECUTION ───────────────────────────────────────────────────────
def execute_command_stream(cmd: str, timeout: int = None) -> str:
    print(f"💻 Executing Command (live output): {cmd}\n")
    proc = subprocess.Popen(cmd, shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True)
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

# ─── LLM INTERACTION ─────────────────────────────────────────────────────────
def chat_with_llm(message: str) -> str:
    chat_history.append({"role": "user", "content": message})
    prompt = "".join(f"{m['role']}: {m['content']}\n" for m in chat_history)
    resp = requests.post(
        OLLAMA_API_URL,
        json={"model": OLLAMA_MODEL,
              "prompt": prompt,
              "stream": False,
              "temperature": 0.3},
        timeout=120
    )
    data = resp.json()
    text = data.get("response") or data.get("choices", [{}])[0].get("text", "")
    reply = text.strip()
    chat_history.append({"role": "assistant", "content": reply})
    return reply

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def extract_command(text: str) -> str:
    """
    Pull out exactly one bash command from the LLM's reply,
    expecting it to be in a ```bash ... ``` code block.
    """
    m = re.search(r"```bash\s*(.*?)\s*```", text, re.DOTALL)
    block = m.group(1) if m else text
    lines = []
    for line in block.splitlines():
        stripped = line.strip().lstrip('$').strip()
        # Skip empty lines, comments, or NOTE: lines
        if not stripped or stripped.startswith('#') or stripped.upper().startswith('NOTE:'):
            continue
        lines.append(stripped)
    # Join multiple lines into a single command chain with &&
    return ' && '.join(lines)

def parse_and_store_notes(text: str):
    """
    Look for lines in LLM output that begin with NOTE:
    append those lines to NOTES_FILE.
    """
    for line in text.splitlines():
        if line.strip().upper().startswith('NOTE:'):
            with open(NOTES_FILE, 'a') as f:
                f.write(line.strip() + '\n')

def fetch_kali_tool_page(toolname: str) -> str:
    """
    Fetch the Kali Tools webpage for <toolname> and return
    its H1 title + a short snippet of the description.
    """
    url = f"https://www.kali.org/tools/{toolname}"
    print(f"🌐 Fetching Kali tool page: {url}")
    resp = requests.get(url, timeout=10)
    if resp.status_code != 200:
        return f"Could not fetch tool info for {toolname} (status {resp.status_code})"
    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.find("h1").get_text(strip=True) if soup.find("h1") else toolname
    # Grab only the first 500 characters of the main description
    desc_div = soup.find("div", class_="post-content")
    desc = desc_div.get_text(strip=True)[:500] if desc_div else ""
    return f"{title} — {desc}\nMore: {url}"

def fetch_web_results(query: str) -> str:
    """
    Use duckduckgo-search (pip install duckduckgo-search) to fetch
    top 5 result titles+URLs for <query>.
    """
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=5):
            title = r.get('title')
            href = r.get('href')
            results.append(f"- {title} ({href})")
    return "\n".join(results) if results else "No results found."

# ─── SESSION SAVE/LOAD ───────────────────────────────────────────────────────
def save_session():
    """
    Write the current chat_history to SESSION_FILE in JSON format.
    """
    with open(SESSION_FILE, 'w') as f:
        json.dump({"chat_history": chat_history}, f, indent=2)

# ─── MAIN WORKFLOW ────────────────────────────────────────────────────────────
COMMAND_FAILURE_PATTERNS = [r"command not found", r"not found"]

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 deepseek_shell.py \"task description\"")
        sys.exit(1)
    task = " ".join(sys.argv[1:])
    print(f"🎯 Task: {task}\n")
    user_msg = f"Task: {task}"
    empty_retries = 0

    try:
        while True:
            # Ask the LLM for the next command (or for special triggers like TOOL_PAGE / WEB_SEARCH)
            llm_out = chat_with_llm(
                user_msg
                + "\nProvide the next bash command in a markdown code block labeled 'bash'."
            )
            print("🧠 LLM Response:\n", llm_out, "\n")

            # 1) Check if LLM wants a Kali tool page
            tool_match = re.search(r"TOOL_PAGE:\s*(\w+)", llm_out)
            if tool_match:
                toolname = tool_match.group(1)
                info = fetch_kali_tool_page(toolname)
                user_msg = f"Tool info for {toolname}:\n{info}"
                continue

            # 2) Check if LLM wants a DuckDuckGo search
            web_match = re.search(r"WEB_SEARCH:\s*(.+)", llm_out)
            if web_match:
                query = web_match.group(1)
                info = fetch_web_results(query)
                user_msg = f"Web results for '{query}':\n{info}"
                continue

            # 3) Store any NOTE: lines to NOTES_FILE
            parse_and_store_notes(llm_out)

            # 4) Extract the bash command from the LLM reply
            cmd = extract_command(llm_out)
            if not cmd:
                empty_retries += 1
                if empty_retries >= MAX_EMPTY_RETRIES:
                    user_msg = (
                        "ERROR: You must output exactly one bash command inside a 'bash' "
                        "code block with no placeholders."
                    )
                    empty_retries = 0
                    continue
                else:
                    # Let LLM try again
                    continue

            # Reset retry counter if a valid command was extracted
            empty_retries = 0

            # 5) Execute the command and print live output
            output = execute_command_stream(cmd)
            print(f"\n📤 Collected Output:\n{output}\n")

            # 6) If it fails, ask LLM for an alternative
            if any(re.search(pat, output, re.IGNORECASE) for pat in COMMAND_FAILURE_PATTERNS):
                user_msg = (
                    f"WARNING: The last command failed with error:\n{output}\n"
                    "Propose an alternative valid command without placeholders in a bash code block."
                )
                continue

            # 7) If the LLM said TASK COMPLETE, we exit
            if re.search(r"TASK COMPLETE", llm_out, re.IGNORECASE):
                print(f"✅ Task complete. Check {NOTES_FILE} for notes. Exiting.")
                break

            # 8) Otherwise, give the next context (command + output) back to the LLM
            user_msg = f"Command: {cmd}\nOutput:\n{output}"

    except KeyboardInterrupt:
        print("\nInterrupted by user. Saving session and exiting.")
    finally:
        save_session()

if __name__ == "__main__":
    main()
