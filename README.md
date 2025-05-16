#Shell Assistant
---
Shell Assistant is a command-line tool that acts like an AI-powered terminal buddy. You describe what you want to do — like “install nginx and start the service” — and it figures out the necessary bash commands, runs them, and keeps going until the task is complete.

It uses OpenAI’s GPT models behind the scenes, so it’s smart about translating your intent into real, working shell commands. It even installs missing tools automatically (using sudo -y), and keeps a short memory of the session to track progress.
What It Can Do

    Turns natural language instructions into bash commands

    Automatically installs missing packages using sudo

    Resolves hostnames before executing commands for speed

    Remembers the last 10 messages in the session

    Runs everything live in the terminal with feedback

What You Need

    Python 3.7 or higher

    The openai Python package (pip install openai)

    An OpenAI API key (with access to a model like gpt-4o-mini)

How to Use It

Once you’ve added your OpenAI API key into the script, just run it from the command line with your task written as plain English. For example:

python3 Ai.py "create a new user called dev and give sudo rights"

The assistant will respond with something like:

sudo adduser dev
sudo usermod -aG sudo dev

Then it will run those commands and continue suggesting the next steps until the task is done. When it reaches the end, it’ll simply say “TASK COMPLETE”.
Configuration

You can fine-tune the assistant’s behavior by editing a few variables in the script:

    MODEL_NAME – which OpenAI model to use

    TEMPERATURE – controls creativity vs. precision (lower is more predictable)

    MAX_TOKENS – length limit for each reply

    MAX_HISTORY_LENGTH – how many previous messages to keep in memory

A Word of Caution

This tool executes real shell commands, including those with sudo. It is meant to be used in a safe development environment (like a test VM or container). Avoid using it on production systems unless you know exactly what it’s doing.
Ideas for the Future

    “Safe mode” that asks before executing commands

    Docker support for safer testing environments

    Plugin support to handle more complex workflows

Contributing

Contributions are welcome! If you’d like to help improve the tool, fix bugs, or suggest new features, feel free to open an issue or submit a pull request.
---
#licence
idk what to put here :)
