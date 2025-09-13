#!/usr/bin/env python3
"""
bagely_repl.py
Interactive terminal assistant that roleplays "Bagely" (fictional).
Features:
- Persona: Bagely-like voice (clearly fictional). System prompt enforces refusal for illegal actions.
- Persistent memory stored in ~/.bagely_memory.json
- Session history stored in ~/.bagely_session.json
- Web browsing via requests + BeautifulSoup:
    - /search <query> -> DuckDuckGo HTML scrape
    - /browse <url> -> fetch and summarize page title and snippet
- Uses pytgpt.phind backend. Falls back to returning error if not available.
- Extracts bash code blocks and prompts to run them.
- Slash commands: /help, /memory add|list|find <q>, /forget <id>, /search, /browse, /run, /auto, /exit
Security:
- Explicitly refuses to help with unauthorized access, exploitation, or other illegal activity.
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup

# Optional colors
try:
    from colorama import init as _init_col, Fore, Style
    _init_col(autoreset=True)
except Exception:
    class _C: RED=GREEN=YELLOW=BLUE=MAGENTA=CYAN=WHITE=""
    class _S: RESET_ALL=""
    Fore, Style = _C, _S

# Files
SESSION_FILE = os.path.expanduser("~/.bagely_session.json")
MEMORY_FILE = os.path.expanduser("~/.bagely_memory.json")

# Limits
MAX_HISTORY = 200
MAX_RETRIES = 3
RETRY_DELAY = 1
CMD_TIMEOUT = 30

# Persona and system prompt
SYSTEM_PROMPT = (
    "You are roleplaying Bagely, a fictional, witty, efficient hacker persona inspired by a video game character. "
    "You must always: (1) state you are fictional when asked, (2) refuse to assist with unauthorized access, exploitation, or illegal activity, "
    "and (3) behave as a concise, direct assistant for reasonable, lawful sysadmin and developer tasks. "
    "When suggesting shell commands wrap them in a bash code block. Keep replies short and factual."
)

PERSONA_INSTRUCTION = (
    "Persona specifics: reply in short, slightly sardonic Bagely-like phrasing. "
    "Do not claim to be a real person. Do not provide instructions for illegal activity."
)

# -------------------------
# Session & memory helpers
# -------------------------
def load_json_file(path: str, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json_file(path: str, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def load_session() -> List[Dict]:
    return load_json_file(SESSION_FILE, [{"role":"system","content": SYSTEM_PROMPT + "\n" + PERSONA_INSTRUCTION}])

def save_session(chat_history: List[Dict]):
    save_json_file(SESSION_FILE, chat_history[-MAX_HISTORY:])

def load_memory() -> List[Dict]:
    return load_json_file(MEMORY_FILE, [])

def save_memory(mem: List[Dict]):
    save_json_file(MEMORY_FILE, mem)

def add_memory(text: str):
    mem = load_memory()
    item = {"id": int(time.time()*1000), "text": text, "ts": time.time()}
    mem.append(item)
    save_memory(mem)
    return item

def list_memory():
    return load_memory()

def find_memory(query: str):
    q = query.lower()
    return [m for m in load_memory() if q in m["text"].lower()]

def forget_memory(mem_id: int):
    mem = load_memory()
    new = [m for m in mem if m["id"] != mem_id]
    save_memory(new)
    return len(mem) != len(new)

# -------------------------
# Phind client wrapper
# -------------------------
try:
    import pytgpt.phind as phind  # type: ignore
except Exception as e:
    phind = None

_PHIND_BOT = None
def _init_phind():
    global _PHIND_BOT
    if _PHIND_BOT is None:
        if not phind:
            return None
        _PHIND_BOT = phind.PHIND()
    return _PHIND_BOT

def chat_with_llm(message: str, chat_history: List[Dict]) -> str:
    """
    Append user message to chat_history, call phind, append assistant reply.
    Returns assistant reply or error string.
    """
    chat_history.append({"role":"user","content":message})
    save_session(chat_history)
    context = "\n".join(f"{m['role']}: {m['content']}" for m in chat_history[-60:])
    last_err = None
    for attempt in range(1, MAX_RETRIES+1):
        try:
            bot = _init_phind()
            if not bot:
                last_err = "pytgpt.phind not available"
                break
            reply = bot.chat(context).strip()
            if reply:
                chat_history.append({"role":"assistant","content": reply})
                save_session(chat_history)
                return reply
            last_err = "empty reply"
        except Exception as e:
            last_err = str(e)
        time.sleep(RETRY_DELAY)
    fail = f"[LLM ERROR] {last_err}"
    chat_history.append({"role":"assistant","content": fail})
    save_session(chat_history)
    return fail

# -------------------------
# Web browsing helpers (requests + BeautifulSoup)
# -------------------------
DDG_HTML = "https://html.duckduckgo.com/html/"

def web_search_ddg(query: str, max_results: int = 5) -> List[Dict]:
    """
    Perform a DuckDuckGo HTML search via requests and parse results.
    Returns list of {title, href, snippet}.
    """
    try:
        resp = requests.post(DDG_HTML, data={"q": query}, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for r in soup.select(".result__body"):
            a = r.select_one("a.result__a")
            snippet = r.select_one(".result__snippet")
            if a:
                title = a.get_text(strip=True)
                href = a.get("href")
                results.append({
                    "title": title,
                    "href": href,
                    "snippet": snippet.get_text(strip=True) if snippet else ""
                })
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        return [{"title": "error", "href": "", "snippet": str(e)}]

def fetch_and_summarize(url: str, max_chars: int = 1000) -> Dict:
    """
    Fetch URL via requests. Return title, text_snippet (first max_chars non-whitespace chars), status_code.
    """
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent":"bagely-repl/1.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else url
        # get main text fallback
        texts = " ".join([p.get_text(" ", strip=True) for p in soup.find_all("p")])
        snippet = (texts[:max_chars] + "...") if len(texts) > max_chars else texts
        return {"title": title, "snippet": snippet, "status": resp.status_code}
    except Exception as e:
        return {"title": url, "snippet": f"error: {e}", "status": None}

# -------------------------
# Command extraction & execution
# -------------------------
def extract_command(text: str) -> Optional[str]:
    m = re.search(r"```(?:bash|sh)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    block = m.group(1) if m else text
    lines = []
    for l in block.splitlines():
        s = l.strip()
        if not s:
            continue
        s = re.sub(r'^\s*[$>]\s*', '', s)
        lines.append(s)
    if not lines:
        return None
    return " && ".join(lines)

def is_shell_command(cmd: str) -> bool:
    if not cmd: return False
    first = cmd.split()[0].lower()
    convo_starts = {"hi","hello","hey","thanks","thank","please","how","what","who","when","where","why"}
    if first in convo_starts:
        return False
    if re.search(r'(^/|^\./|;|\||&&|>|<)', cmd):
        return True
    shell_tools = r'\b(ls|cat|grep|awk|sed|curl|wget|ping|ssh|scp|sudo|apt|yum|dnf|pip|python|node|docker|kubectl|systemctl|nmap|nc|telnet)\b'
    if re.search(shell_tools, cmd, re.IGNORECASE):
        return True
    if len(cmd.split()) <= 2 and re.match(r'^[\w\-\./]+(?:\s+[\w\-\./]+)?$', cmd):
        return True
    return False

def execute_command_stream(cmd: str, timeout: int = CMD_TIMEOUT) -> (str,int):
    print(Fore.GREEN + f"\n💻 Executing: {cmd}\n" + Style.RESET_ALL)
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out_lines = []
    try:
        for line in proc.stdout:
            print(Fore.WHITE + line, end="")
            out_lines.append(line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out_lines.append(f"\n[NOTE] Command timed out after {timeout}s\n")
        print(Fore.YELLOW + f"\n[NOTE] Command timed out after {timeout}s\n")
    ret = proc.returncode if proc.returncode is not None else -1
    return "".join(out_lines).strip(), ret

# -------------------------
# REPL loop
# -------------------------
def print_help():
    print(
        "/help                 show this help\n"
        "/memory add <text>    store a memory\n"
        "/memory list          list memories\n"
        "/memory find <q>      search memories\n"
        "/forget <id>          delete memory id\n"
        "/search <query>       web search (DuckDuckGo)\n"
        "/browse <url>         fetch page summary\n"
        "/run <cmd>            run a shell command locally\n"
        "/auto                 toggle auto-exec of suggested commands\n"
        "/history              show recent chat history\n"
        "/clear                clear session history\n"
        "/exit                 quit\n"
    )

def repl_loop(chat_history: List[Dict], auto_exec: bool = False):
    print(Fore.CYAN + "Bagely REPL. Type /help for commands. Persona: Bagely (fictional)." + Style.RESET_ALL)
    while True:
        try:
            user_in = input(Fore.BLUE + "\nYou> " + Style.RESET_ALL).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            return
        if not user_in:
            continue
        # slash commands
        if user_in.startswith("/"):
            parts = user_in.split(maxsplit=2)
            cmd = parts[0].lower()
            if cmd in ("/exit", "/quit"):
                print("Goodbye.")
                return
            if cmd == "/help":
                print_help(); continue
            if cmd == "/memory" and len(parts) >= 2:
                sub = parts[1].lower()
                if sub == "add" and len(parts) == 3:
                    item = add_memory(parts[2])
                    print(f"Memory saved id={item['id']}")
                elif sub == "list":
                    mem = list_memory()
                    if not mem:
                        print("No memories.")
                    else:
                        for m in mem:
                            print(f"{m['id']}: {m['text'][:200]}")
                elif sub == "find" and len(parts) == 3:
                    found = find_memory(parts[2])
                    if not found:
                        print("No matches.")
                    else:
                        for m in found:
                            print(f"{m['id']}: {m['text'][:200]}")
                else:
                    print("Usage: /memory add|list|find")
                continue
            if cmd == "/forget" and len(parts) >= 2:
                try:
                    mid = int(parts[1])
                    ok = forget_memory(mid)
                    print("Forgotten." if ok else "Not found.")
                except Exception:
                    print("Invalid id.")
                continue
            if cmd == "/search" and len(parts) >= 2:
                query = user_in[len("/search "):].strip()
                print(Fore.YELLOW + f"Searching: {query}" + Style.RESET_ALL)
                results = web_search_ddg(query, max_results=6)
                for i, r in enumerate(results,1):
                    print(f"{i}. {r['title']}\n   {r['href']}\n   {r['snippet']}\n")
                # also add brief note to memory optionally
                continue
            if cmd == "/browse" and len(parts) >= 2:
                url = user_in[len("/browse "):].strip()
                print(Fore.YELLOW + f"Fetching: {url}" + Style.RESET_ALL)
                info = fetch_and_summarize(url)
                print(f"Title: {info['title']}\nStatus: {info['status']}\nSnippet:\n{info['snippet'][:1500]}\n")
                continue
            if cmd == "/run" and len(parts) >= 2:
                sh = user_in[len("/run "):].strip()
                out, rc = execute_command_stream(sh)
                print(f"\n[exit={rc}]\n")
                continue
            if cmd == "/auto":
                auto_exec = not auto_exec
                print("auto-exec:", auto_exec)
                continue
            if cmd == "/history":
                for i, m in enumerate(chat_history[-50:], 1):
                    role = m['role']
                    content = m['content'].replace("\n"," ")
                    print(f"{i:03d} {role}: {content[:200]}")
                continue
            if cmd == "/clear":
                chat_history[:] = [{"role":"system","content": SYSTEM_PROMPT + "\n" + PERSONA_INSTRUCTION}]
                save_session(chat_history)
                print("Session cleared.")
                continue
            print("Unknown command. /help")
            continue

        # normal user message: apply safety quick-check
        unsafe_phrases = ["exploit", "unauthorized", "hack into", "break into", "bypass", "privilege escalation", "exploit kit"]
        if any(p in user_in.lower() for p in unsafe_phrases):
            print(Fore.RED + "Refuse: I will not help with unauthorized or illegal activity." + Style.RESET_ALL)
            continue

        # send to LLM
        reply = chat_with_llm(user_in, chat_history)
        if reply.startswith("[LLM ERROR]"):
            print(Fore.RED + reply + Style.RESET_ALL)
            continue

        # persona: if reply doesn't already state fictionality when asked, ensure it's available when asked by user.
        print(Fore.MAGENTA + "\nBagely> " + Style.RESET_ALL + "\n" + reply + "\n")

        # extract suggestion command
        candidate = extract_command(reply)
        if candidate and is_shell_command(candidate):
            print(Fore.CYAN + f"Suggested command:\n{candidate}\n" + Style.RESET_ALL)
            run_it = auto_exec
            if not auto_exec:
                ans = input("Run this command? [y/N] ").strip().lower()
                run_it = ans in ("y","yes")
            if run_it:
                out, rc = execute_command_stream(candidate)
                # feed output back for follow-up
                follow = f"Command: {candidate}\nExit code: {rc}\nOutput:\n{out}\n\nBased on this, what next?"
                follow_reply = chat_with_llm(follow, chat_history)
                print(Fore.MAGENTA + "\nBagely (follow-up)> " + Style.RESET_ALL + "\n" + follow_reply + "\n")
            else:
                print("Command skipped.")
        else:
            # continue conversationally
            continue

# -------------------------
# CLI
# -------------------------
def main():
    parser = argparse.ArgumentParser(description="Bagely interactive REPL")
    parser.add_argument("--auto-exec", action="store_true", help="auto-run suggested commands")
    parser.add_argument("--no-banner", action="store_true", help="hide banner")
    parser.add_argument("initial", nargs="*", help="optional initial prompt")
    args = parser.parse_args()

    chat_history = load_session()
    if not args.no_banner:
        print(Fore.GREEN + "Bagely REPL - fictional persona; refuses illegal actions." + Style.RESET_ALL)
    if args.initial:
        init_msg = " ".join(args.initial)
        reply = chat_with_llm(init_msg, chat_history)
        print(Fore.MAGENTA + "\nBagely> " + Style.RESET_ALL + "\n" + reply + "\n")
    try:
        repl_loop(chat_history, auto_exec=args.auto_exec)
    finally:
        save_session(chat_history)

if __name__ == "__main__":
    main()
