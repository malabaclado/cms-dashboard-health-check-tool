# Central configuration: CMS endpoints, email recipients, and editable email template text.
# Consumed by get_data.py (URLs), helper_functions.py (emails, templates), and parse_data.py (status_dict).

import os

#======================================================================================
# User-configurable settings
#======================================================================================

# Parameters used for drafting mails to engineers
signoff_name = 'Nick' # Use to change your email signoff name

# Your email
your_email = 'nick.fury@example.com'

# Client services distribution list
team_email ='client.services@example.com'


# Mails of engineer recipients
engineer_mails =[
    'peter.parker@example.com',
    'bruce.banner@example.com',
    'tony.stark@example.com',
    'steve.rogers@example.com'
]

# CC list
cc_mails =[
    team_email
]

# Engineer notification email content — edit these to change what the Step 4
# (engineer notification) email says, without touching helper_functions.py's
# send_mail_to_engineers(). These are plain strings (NOT f-strings): the
# {placeholder} syntax is filled in later via .format() at the point of use,
# since today_date/signoff_name aren't in scope here at import time.
# Available placeholders: {today_date}, {signoff_name}
engineer_email_subject = 'Client IAC Dashboard Monitoring - Import Report Errors ({today_date})'
engineer_email_greeting = (
    "Hello team,<br><br>"
    "In today's Client Dashboard Import Check, we observe the following importer errors:<br><br>"
)
engineer_email_signoff = "<br>Could you please check?<br><br>Best regards,<br>{signoff_name}"



#======================================================================================
# Non-configurable settings (Do not change this unless you know what you are doing)
#======================================================================================


# URLs for scraping data from www.placeholder-url.com
# host is the single source of truth: get_data.get_data() uses it for the Host
# header, and dialogues.py builds the login URL from the same value.
# referrer_* values are sent as the HTTP Referer header in get_data.get_data()
# — the CMS API appears to require a same-origin-looking referrer.
host = 'www.placeholder-url.com'
base_url = f'https://{host}'

url_content = f'{base_url}/healthcheck/content/content'
referrer_content = f'{base_url}/healthcheck/content'

url_importer = f'{base_url}/healthcheck/importers/statuses'
referrer_importer = f'{base_url}/healthcheck/importers'


# Maps the CMS API's numeric status codes to display labels, used by
# parse_data.py's tabular functions (turn_response_content_to_tabular,
# turn_response_importer_to_tabular) when building the 'Status' column.
status_dict = {
    1: 'Healthy',
    2: 'Alert',
    3: 'Error'
}


# ======================================================================
# DEMO MODE (portfolio only): not part of the original tool.
# MOCK_MODE switches the fetch layer from the live CMS API to the JSON files
# in mock_input/. It is ON by default; set the environment variable
# MOCK_MODE=off to run the original HTTP code path instead (it will fail
# against the placeholder URL above).
# simulate_failures is set from main.py's --simulate-failure N option.
# The real fetch logic in get_data.py is unchanged and runs when MOCK_MODE is off.
# ======================================================================
MOCK_MODE = os.getenv('MOCK_MODE', 'on').strip().lower() not in ('off', '0', 'false', 'no')
simulate_failures = 0