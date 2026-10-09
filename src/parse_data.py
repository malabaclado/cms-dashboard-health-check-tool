# Parses the raw JSON/HTML responses from the CMS health check API into two
# shapes: plain text summaries (parse_content_check, parse_import_check — fed
# to write_data.write_to_file) and tabular DataFrames (turn_response_*_to_tabular
# — fed to write_data.save_csv, and from there into the daily email attachments).
#
# NOTE: none of the JSON key lookups here (e.g. response['children'],
# child['status']) use .get() or existence checks — if the CMS dashboard's
# response schema ever changes, these raise KeyError. That's caught generically
# by main.py's flow functions, but the resulting error message won't explain
# that the API schema changed.

import pandas as pd
import sys
from bs4 import BeautifulSoup
import re

from config import status_dict


# Parses a single content-check description's HTML into a (message, entries)
# pair, where entries is a list of {field_label: value} dicts extracted from
# <u>label:</u> value patterns inside a hidden <div>.
def parse_content(content):
    soup = BeautifulSoup(content, features="html.parser")
    message = soup.find('a', class_='healthcheckImporterList').getText(strip=True)

    list_of_dicts = []

    # split by <br/>
    div = soup.find('div', style='display:none;')
    entries_html = str(div.decode_contents()).split('<br/>')

    for entry in entries_html:
        if not entry.strip():
            continue

        pattern = r'<u>([^:]+):\s*</u>\s*([^,<]+)'
        matches = re.findall(pattern, entry)

        entry_dict = {}
        for key, value in matches:
            entry_dict[key.strip()] = value.strip()

        if entry_dict:
            list_of_dicts.append(entry_dict)
    
    return message, list_of_dicts

def parse_content_check(
        response_content: dict
    ) -> list[str]:
    """
    Parse response from content_check and returns list of data to write on file.
    """
    content = response_content['children']
    # Flatten the 2-level tree (asset class -> check type) into a
    # {(asset_title, check_title): description_html} map.
    titles = {}
    for first_level in content:
        content_lvl2 = first_level['children']
        for second_level in content_lvl2:
            titles[(first_level['title'], second_level['title'])] = second_level['description']

    data = []

    for i in titles:
        dict_entry = {}

        if i[0] == 'Structured Products': # exclude structured products
            continue
        
        message, content = parse_content(titles[i])

        dict_entry['title'] = i[0] + ' - ' + i[1]
        dict_entry['message'] = message
        dict_entry['content'] = content

        data.append(dict_entry)

    return data


def flatten_content(content):
    """
    Flatten the JSON response from the importer health check.

    "Flattening" means there are no branches. This function also ignores healthy inputs (status=1)

    Walks the tree level by level (loop runs once per depth), pruning any
    branch whose status == 1 (healthy) and only descending into non-leaf
    nodes. Special-cases the 'M* importer (48 hours) Rating Night file check'
    title: its description is replaced by the child's title instead of the
    normal "parent title + child title" concatenation, since that check's
    per-entry detail lives in the title, not the description.
    """
    skip_list =['Import Log [Error]']

    while all([i['leaf'] for i in content]) != True:
        new_content = []
        for first_level in content:
            
            # skip if ok
            if first_level['status'] == 1:
                continue 

            # retain if no deeper level
            if first_level['leaf'] == True:
                new_content.append(first_level)
                continue

            title = first_level['title']
            children = first_level['children']

            # for each lower level...
            for child in children:
                
                if child['status'] == 1:
                    continue # skip if ok

                if child['title'] in skip_list:
                    continue

                new_dict={}
                
                new_dict['status'] = child['status']
                new_dict['leaf'] = child['leaf']
                new_dict['children'] = child['children']

                # if child['description'] == '': # if description is empty
                if title == 'M* importer (48 hours) Rating Night file check':
                    new_dict['title'] = title
                    new_dict['description'] = child['title'] # set title as description
                    new_content.append(new_dict)
                    continue
                else:
                    new_dict['title'] = title + ' ' + child['title']
                    new_dict['description'] = child['description']
                
                new_content.append(new_dict)
        content = new_content
    return content

# Extracts only the "State : FAILED" entries from the Oddo importer's
# description HTML (other states, e.g. success/pending, are discarded).
def parse_oddo(content):
    soup = BeautifulSoup(content, features="html.parser")
    messages = soup.find_all('span', class_="fulltext-visible")


    # pattern = r'Notification : Document \[(.+?)\] not found'
    filtered_messages =[]
    for message in messages:
        message = message.get_text()
        if 'State : FAILED' in message:
            filtered_messages.append(message)
        else:
            continue

    return filtered_messages

# Splits a Rating/Intraday Errors description on <br /> into a plain-text
# list, one entry per line (each line is a separate ISIN/error record).
def parse_mstar_importer_rating(content):
        parts = content.split('<br />')
        texts = [BeautifulSoup(part, 'html.parser').get_text(strip=True) for part in parts]
        return texts


def parse_import_check(response_content):
    """
    Parse the flattened content from import health check and write it into a list of dictionaries.

    Processes flat_content as a work queue (pop from front each iteration),
    dispatching on entry['title'] to one of several special-case parsers
    (M* rating errors, night file check, Oddo) before falling through to a
    generic handler. "Processed files" entries are dropped entirely (not
    error information); "Night file check" entries with the same title are
    merged into a single accumulating entry instead of creating duplicates.
    """
    content = response_content['children']
    # Initialize the list of dictionaries
    new_data =[]

    # Flatten the content of the JSON response
    flat_content = flatten_content(content)

    # Run while loop while flat_content list is not empty
    while len(flat_content) != 0:

        # Initialize the dictionary per entry
        dict = {}
        entry = flat_content[0]

        # Add counter for debugging
        # dict['item'] = len(flat_content)

        # M* Importer Rating Errors
        if entry['title'] in [
            'M* importer (48 hours) Rating Errors', 
            'M* importer (48 hours) Intraday Errors'
            ]:
            dict['title'] = entry['title']
            dict['content'] = parse_mstar_importer_rating(entry['description'])
            dict['status'] = entry['status']

        # M* importer (48 hours) Rating Night file check
        # Multiple flat_content entries can share this title (one per ISIN);
        # they're merged into a single new_data entry's content list rather
        # than creating one row per ISIN.
        elif 'Night file check' in entry['title']:

            # list all dict['title] each dict in data (list)
            data_keys = [i['title'] for i in new_data if 'title' in i.keys()]

            # if there no night file check in the list of dict['title']: add a new dict
            if entry['title'] not in data_keys:
                dict['title'] = entry['title']
                dict['content'] = [entry['description']]
                dict['status'] = entry['status']

            # if night file check already exists in data, append the new ISIN
            else:
                for i in new_data:
                    if 'title' in i.keys():
                        if i['title'] == entry['title']:
                            i['content'].append(entry['description'])
                flat_content.pop(0)
                continue
        
        # Oddo Importer
        elif 'Oddo CSV, XLSX' in entry['title']:
            dict['title'] = entry['title']
            dict['content'] = parse_oddo(entry['description'])
            dict['status'] = entry['status']


        elif entry['title'] in [
            'M* importer (48 hours) Rating Processed files', 
            'M* importer (48 hours) Intraday Processed files'
            ]:
            flat_content.pop(0)
            continue

        else:
            dict['title'] = entry['title']
            dict['status'] = entry['status']
            if isinstance(entry['description'], list):
                dict['content'] = entry['description']
            else:
                dict['content'] = [entry['description']]

        # add dict to data
        new_data.append(dict)

        # remove entry
        flat_content.pop(0)
    return new_data



# Used only by turn_response_content_to_tabular() (via get_description()) to
# build the "Detail" column of the content-check tabular/CSV export.
def parse_regex_from_description(description: str, assetErrorType: str) -> str:
    """
    Use this function to parse regex from description under different asset and error types.

    Dispatches on assetErrorType to pick the right regex, since each check
    type's description text has a different "ISIN: ..., <field>: ..." shape.
    Returns None (falls through with no explicit return) for any
    assetErrorType not covered by the branches below, or if the regex doesn't
    match — callers must tolerate a None detail value.
    """
    if assetErrorType in ['Funds - Inactive ISINs', 'Equities - Inactive ISINs', 'Bonds - Inactive ISINs']:
        match = re.match(
            r'ISIN:\s*(\S+),\s*Title:\s*(.+)',
            description.strip()
        )
        
        if match:
            isin = match.group(1)
            title = match.group(2).strip()
            # result.append(f"ISIN: {isin}, Title: {title}")
            return f"ISIN: {isin}, Title: {title}"
    elif assetErrorType == 'Funds - NAV prices check':
        match = re.match(
            r'ISIN:\s*(\S+),\s*Nav date:\s*([\d-]*),\s*Title:\s*(.*)',
            description.strip()
        )

        if match:
            isin = match.group(1)
            nav_date = match.group(2).strip()
            title = match.group(3).strip()
            
            # Build the output string
            nav_date_str = f", Nav date: {nav_date}" if nav_date else ""
            return f"ISIN: {isin}{nav_date_str}, Title: {title}"

    elif assetErrorType in ['Equities - Prices check', 'Equities - M* currency check', 'Bonds - PX-Last']:
        match = re.match(
            r'ISIN:\s*(\S+),\s*Last Updated at:\s*([^,]*),\s*Title:\s*(.*)',
            description.strip()
        )

        if match:
            isin = match.group(1)
            last_updated = match.group(2).strip()
            title = match.group(3).strip()

            # Build the output string
            last_updated_str = f", Last Updated at: {last_updated}" if last_updated else ""
            return f"ISIN: {isin}{last_updated_str}, Title: {title}"

    elif 'Equities - Translations inconsistency' in assetErrorType:
        match = re.match(
            r'ISIN:\s*(\S+)\s*$',
            description.strip()
            )

        if match:
            isin = match.group(1)
            return f"ISIN: {isin}"


# Used only by turn_response_content_to_tabular() to expand a single
# child['description'] HTML blob (which can contain multiple <a> sections,
# each with its own hidden <div><br/>-separated entries) into one row per
# entry, pairing each entry with the regex-parsed detail from
# parse_regex_from_description().
def get_description(html_string: str, assetErrorType: str) -> list:
    """
    Parses the raw description (in html format) from responses and returns a list of of list.

    List: [description, detail]
    """
    soup = BeautifulSoup(html_string, 'html.parser')
    result = []
    
    # Find all anchor tags with the healthcheckImporterList class
    sections = soup.find_all('a', class_='healthcheckImporterList')
    
    for section in sections:
        # Extract the section title (remove the "+ " prefix from strong tag)
        title = section.get_text().replace('+ ', '').strip()
        # result.append(f"{title}")
        
        # Find the next sibling div with display:none
        next_div = section.find_next_sibling('div')
        
        if next_div:
            # Extract all text content from the div
            div_content = next_div.decode_contents()
            
            if div_content.strip():
                # Split by <br> tags to get individual entries
                entries = re.split(r'<br\s*/?>', div_content)
                
                for entry in entries:
                    entry = entry.strip()
                    if entry:
                        # Parse each entry using BeautifulSoup
                        entry_soup = BeautifulSoup(entry, 'html.parser')
                        entry_text = entry_soup.get_text()
                        
                        # Extract ISIN and Title using regex
                        result.append([title, parse_regex_from_description(entry_text, assetErrorType)])

                        
    return result

# NOTE: appears to duplicate/overlap parse_content_check() above (both walk
# the same 2-level content-check tree), but this version produces the tabular
# DataFrame used for the CSV export, while parse_content_check() produces the
# plain-text form written by write_data.write_to_file(). Kept separate since
# they serve different output shapes.
def turn_response_content_to_tabular(response: dict)-> pd.DataFrame: # type: ignore
    """
    Turn JSON response from /content/check to DataFrame. This dataframe is saved as a CSV report

    Table Columns:
    - Status (Alert / Error)
    - Asset (Equities / Bonds / Funds)
    - Error Title
    - Description
    - Detail
    """
    rows = []
    columns = ['Status', 'Asset', 'Error Title', 'Description', 'Detail']
    assetErrorTypeToSkip = [
        'Equities - M* Rating check',
        'Funds - Fund rating check (API, CMS, Full Fund List)'
    ]

    for child in response['children']:
        # Skip Structured Products
        if child['title'] == 'Structured Products':
            continue

        # Skip Healthy Status (=1)
        if child['status'] == 1:
            continue

        asset = child['title']

        if child['leaf'] == False:
            for child_ in child['children']:

                # Skip if healthy
                if child_['status'] == 1:
                    continue

                errorType = child_['title']
                desription_html = child_['description']
                

                status = status_dict[child_['status']]

                # Parse description
                assetErrorType = asset + ' - ' + errorType

                if assetErrorType not in assetErrorTypeToSkip:
                    for i in get_description(desription_html, assetErrorType):
                        description = i[0]
                        detail = i[1]

                        # Skip if "Non-Preferred" is in the description
                        if "Non-Preferred" in description and errorType == 'NAV prices check':
                            continue

                        # Add row to rows
                        rows.append([status, asset, errorType, description, detail])
    # 'Description' (the section title from get_description(), i.e. i[0]) is
    # collected only to build the DataFrame shape above, then dropped here —
    # the final table keeps 'Detail' (i[1]) as the actual per-row content.
    return pd.DataFrame(rows, columns=columns).drop(columns=['Description'])

# Used only by turn_response_importer_to_tabular() for the two "Errors"
# entries (Rating/Intraday) to flatten their <span>-wrapped, <br/>-separated
# log lines into a single newline-joined string for the CSV "Details" cell.
def parse_error_log(html_string):
    # Parse the HTML
    soup = BeautifulSoup(html_string, 'html.parser')
    
    # Replace <span> tags with their text content
    for span in soup.find_all('span'):
        span.replace_with(span.get_text())
    
    # Get the full text and split by <br /> tags
    lines = []
    formatted_line = ''
    raw_lines = str(soup).split('<br/>')
    
    for line in raw_lines:
        # Remove any remaining HTML tags
        clean_line = re.sub(r'<[^>]+>', '', line)
        # Strip whitespace and newlines
        clean_line = clean_line.strip()
        
        if clean_line:
            formatted_line += clean_line+'\n'
    
    return formatted_line

# Guards against pathologically large descriptions (seen with some importer
# error dumps) that would bloat the CSV/email — anything >= 28KB gets replaced
# with a placeholder string by the caller instead of being included verbatim.
def check_byte_limit(string):
    size = sys.getsizeof(string)
    # print(f"Size: {size} bytes")
    return size < 28000 # 28KB

# Splits a flattened entry's title (e.g. "Oddo CSV, XLSX Errors") into its
# importer name ("Oddo CSV, XLSX", matched from importer_names — the
# top-level child titles) and the remaining error-type text. Falls back to
# (pd.NA, title) when no known importer name is found in the title.
def split_importer_and_error(title, importer_names):
    for name in importer_names:
        if name in title:
            error_title = title.replace(name, "").strip()
            return name, error_title
    return pd.NA, title

# Turns the flattened importer health check content into a DataFrame (for
# save_csv() -> the importer CSV consumed by send_mail_to_engineers() and
# the email summary). Same flatten_content() tree-walk as parse_import_check(),
# but here every flattened entry becomes one row (no merging), and this
# version additionally splits out an 'Importer' column and truncates
# oversized descriptions via check_byte_limit().
def turn_response_importer_to_tabular(response_importer: dict):
    content = response_importer['children']
    importer_names = [i['title'] for i in content]
    flat_content = flatten_content(content)

    skip_list = [
        'M* importer (48 hours) Intraday Processed files',
        'M* importer (48 hours) Rating Processed files'
    ]


    rows = []
    columns = [
            'Status',
            'Error Title',
            'Details'
        ]

    for item in flat_content:
        if item['title'] in skip_list:
            continue

        # Handle M* importer (48 hours) Rating Night file check
        if item['title'] == 'M* importer (48 hours) Rating Night file check':
            continue

        # Ignore details more than 28KB
        if check_byte_limit(item['description']):
            desc = item['description']
        else:
            desc  = "Details omitted due to large string size (size > 28KB)."


        print(item['title'])
        if item['title'] in ['M* importer (48 hours) Intraday Errors', 'M* importer (48 hours) Rating Errors']:
            desc = parse_error_log(desc)
    
        rows.append(
            [
                status_dict[item['status']],
                item['title'],
                desc
            ]
        )


    # # Separate importer names from error titles
    # for name in importer_names:
    #     if name in item['title']:

    df = pd.DataFrame(rows, columns=columns)

    # Separate importer names from error titles
    df[['Importer', 'Error Title']] = df['Error Title'].apply(
        lambda x: pd.Series(split_importer_and_error(x, importer_names))
    )

    # Sort columns in this order: ['Status', 'Importer', 'Error Title', 'Details']
    df = df[['Status', 'Importer', 'Error Title', 'Details']].rename(
        columns={'Error Title': 'Title'}
    )
    return df