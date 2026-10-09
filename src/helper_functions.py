# Core business logic for the health check / email pipeline, called from main.py.
# Groups: cookie management (modify/update/validate_cookies), Outlook email
# sending (send_outlook_email, create_outlook_email, send_email_summary,
# send_mail_to_engineers), and the health check orchestration (perform_health_check).

import json
from pathlib import Path
import os

import pandas as pd
import win32com.client
from datetime import datetime, timedelta

from dialogues import dialogues
import config  # DEMO MODE (portfolio only): read MOCK_MODE at call time
from config import (
    url_content, url_importer, referrer_content, referrer_importer,
    engineer_mails, team_email, signoff_name, cc_mails,
    engineer_email_subject, engineer_email_greeting, engineer_email_signoff
)
from get_data import fetch_with_retry, extract_regex
from parse_data import parse_content_check, parse_import_check, turn_response_content_to_tabular, turn_response_importer_to_tabular
from write_data import write_to_file, save_csv


def modify_cookies(cookies: dict, key: str, value: any):
    # Update key-value
    cookies[key] = value

    # Write back
    # NOTE: no validation that `value` is non-None before writing — extract_regex()
    # below returns None on a failed regex match, which would silently persist
    # a None value into cookies.json rather than raising an error.
    with open('data/cookies.json', 'w') as f:
        json.dump(cookies, f, indent=2)

def update_cookies(cookies: dict):
    """Interactively refresh stale cookies from a pasted browser cURL command.

    Expects the user to paste a "Copy as cURL (cmd)" request from DevTools
    (see dialogues['refresh_cookies_instruction'] for the exact steps) and
    reads it line-by-line from stdin until a blank 'END' line, extracting the
    CSRF token, session ID, and user analysis values via regex.
    """
    print('Cookies are stale. Please update to ensure the program works correctly.')
    print(dialogues['refresh_cookies_instruction'])

    cookies_updated = False
    print("Enter your text (Press 'ENTER' to finish input):")
    for line in iter(input, ""):
        if '^"X-CSRFToken:' in line:
            x_csrf_token = extract_regex(r'X-CSRFToken: (.+?)\^"', line)
            modify_cookies(cookies=cookies, key="X_CSRF_TOKEN", value=x_csrf_token)
            # update_env("X_CSRF_TOKEN", x_csrf_token)
            # print('X-CSRFTOKEN=' + x_csrf_token)
        elif '^"USER_ANALYSIS' in line:
            print('Started')
            sessionid = extract_regex(r'PHPSESSID=(.+?)\^"',line)
            modify_cookies(cookies=cookies, key="PHPSESSID", value=sessionid)
            # update_env("PHPSESSID", sessionid)
            # print('SESSIONID=' + sessionid)

            csrf_token = extract_regex(r'CSRF_TOKEN=(.+?);',line)
            modify_cookies(cookies=cookies, key="CSRF_TOKEN", value=csrf_token)
            # update_env("CSRF_TOKEN", csrf_token)
            # print('CSRFTOKEN=' + csrf_token)

            user_analysis = extract_regex(r'USER_ANALYSIS=(.+?);',line)
            modify_cookies(cookies=cookies, key="USER_ANALYSIS", value=user_analysis)
            # update_env("USER_ANALYSIS", user_analysis)
            # print('USER_ANALYSIS=' + user_analysis)

            # cookies_updated = TRUE only if Cookie line detected and above code ran
            now = datetime.now()
            modify_cookies(cookies, key='LAST_UPDATED', value = datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            cookies_updated = True
        elif line == '':
            continue
        elif line == 'END':
            break

    if cookies_updated == True:
        print('BROWSER COOKIES UPDATED!')
    else:
        print('BROWSER COOKIES UPDATE FAILED.')
        # NOTE: exit() raises SystemExit, which is a BaseException (not a
        # subclass of Exception) — so it bypasses every `except Exception`
        # handler upstream in main.py, terminating the program immediately
        # without showing the execution summary.
        exit()

def validate_cookies(cookies: dict):
    """Raise no error itself, but triggers an interactive refresh (update_cookies)
    if the cookie's LAST_UPDATED timestamp is older than 6 hours. Called before
    every health check run via load_and_validate_cookies() in main.py.
    """
    # Import cookies['LAST_UPDATED'] as datetime
    last_updated = datetime.strptime(cookies['LAST_UPDATED'], "%Y-%m-%d %H:%M:%S")

    # If last_updated is more than 6 hours from now, update cookies
    if datetime.now() - last_updated > timedelta(hours=6):
        update_cookies(cookies)


def get_attachments():
    """Collect today's content/importer CSV paths for the team email attachments.
    Missing files are logged and skipped rather than raising; returns None if
    neither CSV is found (rather than an empty list) so callers can branch on it.
    """
    attachments =[]
    tags = ['content', 'importer']
    for tag in tags:
        csv_file_path = os.path.abspath(r"data\daily_check\csv")
        filename = datetime.now().strftime("%Y%m%d") + f"_{tag}-check.csv"
        filepath = Path(csv_file_path + '/' + filename)
        

        if os.path.exists(filepath):
            attachments.append(str(filepath))
        else:
            print(f"CSV file not found: {str(filepath)}")

    if len(attachments) == 0:
        return None
    else: 
        return attachments

def send_outlook_email(to, subject, body, attachments=None):
    """Sends outlook mail immediately via mail.Send() — no user review step.

    Used only for the team summary email (send_email_summary). Contrast with
    create_outlook_email() below, which opens a draft for manual review instead
    of sending automatically (used for the engineer notification).

    NOTE: no try/except around win32com.client.Dispatch — if Outlook isn't
    installed/running, or COM automation is unavailable (e.g. a non-interactive
    Windows session such as a scheduled task with no logged-in desktop), this
    raises pywintypes.com_error, which propagates up and is caught generically
    by main.py's send_email_summary_flow().
    """
    # Create Outlook application
    outlook = win32com.client.Dispatch("Outlook.Application")
    
    # Create a new email
    mail = outlook.CreateItem(0)  # 0 = mail item
    mail.To = to
    mail.Subject = subject
    mail.Body = body
    
    # Add attachments if provided
    if attachments:
        for attachment in attachments:
            mail.Attachments.Add(attachment)
    
    # Send the email
    mail.Send()
    print("Email sent successfully!")


def send_email_summary(has_body = False):
    """Send the daily team summary email (Step 3 in main.py).

    Requires today's content/importer .txt files to already exist under
    daily_check/ (written by perform_health_check -> write_to_file); raises
    FileNotFoundError immediately if either is missing, rather than deferring
    to a less clear error later. has_body=False (the default) sends a short
    notice pointing to the CSV attachments instead of inlining the full text.
    """
    # Check if today's files exists
    dateToday = datetime.now().strftime("%Y-%m-%d")
    content_file = f"data/daily_check/content/{dateToday}_content-check.txt"
    importer_file = f"data/daily_check/importer/{dateToday}_importer-check.txt"

    if not os.path.exists(content_file):
        raise FileNotFoundError(f"Content file not found: {content_file}")
    if not os.path.exists(importer_file):
        raise FileNotFoundError(f"Importer file not found: {importer_file}")

    with open(content_file, "r", encoding="utf-8") as f:
        content_text = f.read()

    # Skip the first line (the "Timestamp: ..." header written by write_to_file)
    # since it's not meant to appear in the email body when has_body=True.
    # NOTE: if the file is empty (e.g. a partially-written/truncated file),
    # next(f) raises StopIteration here.
    with open(importer_file, "r", encoding="utf-8") as f:
        next(f)
        importer_text = f.read()

    from config import team_email

    subject = f'Client Daily Check Summary {dateToday}'
    end_line = "---------- END ----------"


    if has_body:
        body = content_text + importer_text + end_line
    else:
        body = "Please see the attached files for today's content and importer health check."

    attachments = get_attachments()

    # ======================================================================
    # DEMO MODE (portfolio only): not part of the original tool.
    # In demo mode the summary email is not sent: send_outlook_email() is
    # skipped, so no Outlook is needed and nothing can block on an Outlook
    # dialog. Everything above (file checks, subject, body, attachments)
    # still runs. The step is reported as successful.
    # The real send logic below is unchanged and runs when MOCK_MODE is off.
    # ======================================================================
    if config.MOCK_MODE:
        print(f"Demo mode: email to {team_email} not sent (Outlook skipped).")
        print(f"Subject    : {subject}")
        print(f"Attachments: {len(attachments) if attachments else 0}")
        return

    send_outlook_email(team_email, subject, body, attachments)

def perform_health_check():
    """Executes both content and importer health check.
    
    Execution: 
    > Downloads data from API 
    > Parses information from JSON response
    > Saves content/importer check summary in a .txt file
    """
    # Perform Content Health Check
    # fetch_with_retry -> get_data() now raises on any failure (HTTP error,
    # SSL/connection error, empty body, invalid JSON) instead of returning
    # None, so retry_with_backoff can actually retry these failures and the
    # real exception (not a downstream NoneType error) surfaces if all
    # retries are exhausted.
    print('\nPerforming Content Health Check...')
    response_content = fetch_with_retry(
        url_content,
        referrer_content,
        tag='content',
        max_retries=3
    )
    
    print('Parsing response...')
    data = parse_content_check(response_content)
    table_content = turn_response_content_to_tabular(response_content)

    print('Saving to file...')
    write_to_file(data)
    save_csv(table_content, tag='content')

    
    # Perform Importer Health Check
    print('\nPerforming Importer Health Check...')

    # Retries with exponential backoff
    response_importer = fetch_with_retry(
        url_importer,
        referrer_importer,
        tag='importer',
        max_retries=3
    )

    print('Parsing response...')
    data = parse_import_check(response_importer)
    table_importer = turn_response_importer_to_tabular(response_importer)
    

    print('Saving to file...')
    write_to_file(data, tag='importer')
    save_csv(table_importer, tag='importer')
    
    print('RUN SUCCESSFUL')

def create_outlook_email(to, subject, body, cc=None, bcc=None, attachments=None):
    """
    Create and open a new Outlook mail window with pre-filled content.

    Unlike send_outlook_email(), this calls mail.Display() instead of
    mail.Send() — the draft is left open for the user to review/edit before
    manually sending. Used by send_mail_to_engineers() for the engineer
    notification, which should always be reviewed before going out.

    Args:
        to: recipient email or list of emails
        subject: email subject
        body: email body text
        cc: optional CC recipients (email or list)
        bcc: optional BCC recipients (email or list)
        attachments: optional list of file paths to attach
    """
    # Create Outlook application object
    outlook = win32com.client.Dispatch('Outlook.Application')
    
    # Create a new mail item (0 = olMailItem)
    mail = outlook.CreateItem(0)
    
    # Set basic properties
    mail.To = to if isinstance(to, str) else '; '.join(to)
    mail.Subject = subject
    mail.HTMLBody = body
    
    if cc:
        mail.CC = cc if isinstance(cc, str) else '; '.join(cc)
    if bcc:
        mail.BCC = bcc if isinstance(bcc, str) else '; '.join(bcc)
    
    # Add attachments if provided
    if attachments:
        for file_path in attachments:
            mail.Attachments.Add(file_path)
    
    # Display the mail window (unsent, so user can review)
    mail.Display()

def send_mail_to_engineers():
    """Draft (not send) the engineer notification email (Step 4 in main.py).

    Reads today's importer CSV, filters to rows with Status == 'Error', and
    renders them as an HTML table in the email body. If there are no errors,
    a placeholder message is shown instead. The email is opened via
    create_outlook_email() (mail.Display()) for manual review, not auto-sent.
    Greeting/signoff/subject text come from config.py's engineer_email_* templates.
    """
    # Build email body (html table)
    csv_file_path = os.path.abspath(r"data\daily_check\csv")
    filename = datetime.now().strftime("%Y%m%d") + f"_importer-check.csv"
    filepath = Path(csv_file_path + '/' + filename)

    # Guard against a missing/malformed CSV (e.g. importer check never ran,
    # or failed before writing the file) with a clear, actionable error
    # instead of letting pandas raise an opaque FileNotFoundError/KeyError.
    if not filepath.exists():
        raise FileNotFoundError(
            f"Importer CSV not found: {filepath}. Run the health check step first."
        )

    df = pd.read_csv(filepath, sep='|')

    if 'Status' not in df.columns:
        raise ValueError(
            f"Importer CSV at {filepath} is missing the 'Status' column — "
            "check that the importer health check completed successfully."
        )

    df = df[df['Status'] == 'Error']
    
    if len(df) == 0:
        df_html = '<i>[There are no importer errors recorded. Support may still send an email if necessary. Please feel free to attach screenshots from the dashboard.]</i><br>'
    else:
        df_html = df.to_html(index=None)

    today_date = datetime.now().strftime("%Y-%m-%d")
    opening = engineer_email_greeting
    signoff = engineer_email_signoff.format(signoff_name=signoff_name)
    email_body = opening + df_html + signoff
    subject = engineer_email_subject.format(today_date=today_date)



    create_outlook_email(
        to= engineer_mails,
        subject=subject,
        body = email_body,
        cc= cc_mails,
        # attachments=['C:\\path\\to\\file.pdf']
    )