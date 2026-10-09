# Client Dashboard Health Check Tool

A Python command-line tool that automates a daily monitoring routine: pulling the content and importer health statuses from a client's CMS dashboard, filtering them down to what needs attention, saving the results as text and CSV reports, emailing a summary to the team, and drafting an error report for the engineers. It replaces a manual check-and-copy routine with a repeatable, four-step workflow that still keeps a human in the loop before anything is sent to engineers.

## Disclaimer

This is a portfolio copy of a tool built for real work, and it has been anonymized.

- **Client details are removed or replaced.** The customer name, dashboard URL, email addresses and engineer names are placeholders (`Client`, `www.placeholder-url.com`, `example.com` addresses, fictional names).
- **The sample data is a snapshot.** The files in `mock_input/` were derived from real health check responses. The customer name was removed from the file names and the connection details, but the fund and asset names, vendor names and statuses inside them are kept so the parsers have realistic input. These are public market data, and some fund names include the name of a well-known bank.
- **It runs as a mock, for demo purposes only.** By default the tool does **not** call any live service. It reads the sample responses from `mock_input/` and shows the same workflow end to end. The placeholder URL is not a real endpoint, so the live code path will fail if you switch demo mode off.
- **Nothing is monitored.** The results you see are the same sample data on every run.

## Architecture and Design

The tool is a linear pipeline driven by an interactive CLI: fetch, parse, write, then notify.

```
main.py (CLI flow, rich output)
   │
   ▼
helper_functions.py ── orchestrates each step
   │         │
   │         ├── get_data.py ─────► live API (or mock_input/ in demo mode)
   │         ├── parse_data.py ───► filters and flattens the JSON/HTML responses
   │         └── write_data.py ───► data/responses/, data/daily_check/ (txt + csv)
   │
   └── Outlook (COM): summary email, engineer draft
```

### Project structure

```
.
├── main.py                  CLI entry point: the 4-step workflow
├── config.py                Settings: URLs, email recipients, email templates, demo switch
├── requirements.txt         Python dependencies
├── documentation.md         What is recorded in the reports and what is filtered out
├── src/
│   ├── get_data.py          Fetching, retry with backoff, demo-mode mock fetch
│   ├── parse_data.py        Parsing and filtering of the API responses
│   ├── write_data.py        Writing raw responses, text reports and CSV files
│   ├── helper_functions.py  Cookie handling, health check orchestration, email
│   └── dialogues.py         Text shown to the user (cookie refresh instructions)
├── mock_input/              Sample API responses and a sample cookie paste (demo)
│   ├── content-check.json
│   ├── importer-check.json
│   ├── sample_cookies.txt
│   └── 2026-09-28_*         Backup sample inputs (not read by the code)
└── data/
    └── cookies.json         Saved browser session cookies
```

Created when you run it: `data/responses/` (raw responses) and `data/daily_check/` (`content/`, `importer/` and `csv/` reports).

### Key modules

| Module | What it does |
|--------|--------------|
| `main.py` | Runs the interactive flow with [rich](https://github.com/Textualize/rich) panels and spinners: check today's data, validate cookies and run the health check, send the summary email, draft the engineer email. Prints an execution summary at the end. `--auto` answers every prompt with its default. |
| `config.py` | One place for the settings: the endpoint URLs (built from a single host value), the sender and recipient addresses, the engineer email subject, greeting and signoff templates, and the status code mapping (1 Healthy, 2 Alert, 3 Error). |
| `src/get_data.py` | Fetches the two API responses with browser-style headers and cookies. Every failure path raises, so `retry_with_backoff()` can retry with exponential delays (5 s, 10 s, 20 s, capped at 30 s). In demo mode `get_mock_data()` returns the sample JSON instead of making a request. |
| `src/parse_data.py` | The core logic. Flattens the nested response tree, drops healthy entries and noise, extracts ISINs, titles and error messages from the embedded HTML with BeautifulSoup and regex, and produces both plain-text summaries and pandas DataFrames. |
| `src/write_data.py` | Saves the raw response, the daily `.txt` reports and the pipe-delimited CSV files. Creates its output folders on first use. |
| `src/helper_functions.py` | Cookie lifecycle (load, check age, refresh from a pasted cURL command), the health check orchestration, and the email functions that talk to Outlook. |
| `src/dialogues.py` | The step-by-step cookie refresh instructions shown to the user. |

The code that exists only for the demo is marked with a `DEMO MODE (portfolio only)` comment block. Search for that phrase to see exactly what was added to the original tool. The real logic is unchanged and runs when demo mode is off.

## Features

- **Four-step interactive workflow** with clear prompts, spinners and a final execution summary.
- **Unattended mode** (`--auto`) that takes the default at each prompt, for scheduled runs.
- **Content health check** that keeps only Alert and Error entries, skips empty "no issues" messages and excluded asset classes, and extracts the details of each affected item.
- **Importer health check** that flattens the importer tree, merges duplicate night file checks, converts HTML error logs to plain text, and truncates oversized descriptions (over 28 KB).
- **Reports in two formats**: a readable `.txt` summary and pipe-delimited `.csv` files per check.
- **Retry with exponential backoff** for transient network failures.
- **Session cookie management**: detects cookies older than 6 hours and walks the user through refreshing them from a pasted browser cURL command.
- **Summary email** with both CSV reports attached (sent through Outlook).
- **Engineer notification draft** containing only the importer Error rows as an HTML table, opened for review instead of being sent automatically.
- **Editable email templates** for the subject, greeting and signoff in `config.py`.
- **Demo mode** that runs the whole workflow offline from sample data, with `--simulate-failure N` to show the retry and backoff behavior.

The filtering rules are described in detail in [documentation.md](documentation.md).

## Demo Guide

### Requirements

- Windows (the email steps use Outlook through COM)
- Python 3.10
- Classic Outlook installed, for Step 4 (the engineer email draft). Step 3 does not need Outlook in demo mode.

### Setup on a new machine

1. Install Python 3.10 and check it with `py --version`.
2. Get this folder onto the machine (clone or download it) and open a terminal inside it.
3. Install the dependencies:
   ```
   py -m pip install -r requirements.txt
   ```

### Run the demo

```
py main.py
```

1. **Step 1** reports whether today's data already exists.
2. **Step 2** asks to run the health check. The saved cookies are older than 6 hours, so the tool shows the cookie refresh instructions. In demo mode there is no login, so open `mock_input/sample_cookies.txt`, paste its whole contents into the terminal, then press Enter on an empty line. The tool reports that the cookies were updated, then fetches both checks and writes the reports. Look in `data/responses/` and `data/daily_check/` for the output.
3. **Step 3** shows the summary email step. In demo mode it prints the recipient, subject and attachment count and does not send anything.
4. **Step 4** drafts the engineer email and opens it in Outlook for review. It is addressed to the sample `example.com` engineers and lists the importer errors. Answer `n` at this prompt if you have no Outlook, or if you don't want a draft window to open.

### Other things to try

| Command | What it shows |
|---------|---------------|
| `py main.py --simulate-failure 1` | The first fetch of each check fails, then the retry and backoff output, then success. |
| `py main.py --auto` | The unattended flow. Refresh the cookies once first (step 2 above), because stale cookies stop `--auto` at the paste prompt. |
| `$env:MOCK_MODE = 'off'` then `py main.py` | Switches demo mode off (PowerShell). The tool then tries the real request, which fails against the placeholder URL. This is expected. |

### Good to know

- Running the demo overwrites `data/cookies.json` with the values from `sample_cookies.txt`, so `git status` shows it as modified afterwards.
- Cookies stay valid for 6 hours. Within that window, later runs skip the paste step.
- If today's data already exists, Step 2 defaults to not re-running it.
- Every run writes a new timestamped file to `data/responses/` with identical content, because the input is a fixed sample file.
