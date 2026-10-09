# File/CSV writing helpers for the health check pipeline.
# write_to_file() writes the plain-text daily_check/{content,importer}/*.txt
# reports; save_csv() writes the daily_check/csv/*.csv files that main.py's
# check_health_check_status() looks for and that send_mail_to_engineers()/
# send_email_summary() (helper_functions.py) read back.

from pathlib import Path
import os
from datetime import datetime
import json
from zoneinfo import ZoneInfo

# Used by write_to_file()'s 'content' branch to render one content-check
# entry's field dict (e.g. {'ISIN': ..., 'Title': ...}) back into a single
# "key: value, key: value" line for the .txt report.
def dict_to_string(dict):
    string = ''
    for i in dict.keys():
        string += i + ': ' + dict[i]

        if i != 'Title':
            string += ', '
    return string

def write_to_file(data: list[str], tag='content'):
    """Saves content-check data to file.

    tag selects both the output directory (daily_check/content or
    daily_check/importer) and which branch below runs, since the 'content'
    and 'importer' input shapes (list of dicts) are formatted differently.
    mkdir(parents=True, exist_ok=True) ensures the tag subdirectory exists
    before the first run creates it.
    """
    today_date = datetime.now().strftime("%Y-%m-%d")
    filename = today_date + f'_{tag}-check'

    path = Path(f'data/daily_check/{tag}') / f"{filename}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, 'w', encoding='utf-8') as f:
        # # Write timestamp
        # timestamp = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
        # f.write('timestamp: ' + str(timestamp) + '\n'*2)

        # Add timestamp
        create_timestamp = 'Timestamp: ' + datetime.now(ZoneInfo('UTC')).strftime("%Y-%m-%d %H:%M:%S %Z")
        f.write(create_timestamp)
        f.write('\n\n')

        if tag == 'importer':
            # 'importer'-tag entries (from parse_import_check()) have
            # 'title' + 'content' (a list of already-formatted strings) —
            # no 'message' key, so no filtering is applied here unlike the
            # 'content' branch below.
            for i in data:
                # if any(phrase in i['message'] for phrase in ["don't exist", "0 Funds exist", "does not exist"]):
                #     continue

                f.write(i['title'])
                
                # f.write(i['message'])
                f.write('\n')

                for line in i['content']:
                    f.write(line)
                    f.write('\n')
            
                f.write('\n')
            print(f'Data saved in \daily_check\{tag}\{filename}.txt')
        
        elif tag =='content':
            # 'content'-tag entries (from parse_content_check()) have
            # 'title' + 'message' + 'content' (list of field dicts). Entries
            # whose message indicates "nothing to report" (e.g. an empty
            # fund universe) are skipped rather than written as empty sections.
            for i in data:
                if any(phrase in i['message'] for phrase in ["don't exist", "0 Funds exist", "does not exist"]):
                    continue

                f.write(i['title'])
                f.write('\n')
                
                f.write(i['message'])
                f.write('\n')

                for row in i['content']:
                    f.write(dict_to_string(row))
                    f.write('\n')
            
                f.write('\n')
            print(f'Data saved as text in \daily_check\{tag}\{filename}.txt')
        else:
            print(f'The tag {tag} is not acceptable')
            pass

# Called from get_data.get_data() after every successful fetch, to persist
# the raw API response for offline replay via get_data.load_response().
# Creates the 'responses' directory on first use, like write_to_file() and
# save_csv() do for their target directories.
def save_response(response, tag='content'):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = timestamp + '_{}-check'.format(tag)

    path = Path('data/responses') / f"{filename}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    # with open(path, 'w',  encoding='utf-8') as f:
    #     f.write(str(response.json()))

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(response.json(), f, indent=2)

def save_csv(df, tag='content'):
    """Saves a dataframe to a CSV file.

    Filename uses the "%Y%m%d" compact date format — this is the same
    filename shape that main.py's check_health_check_status() looks for, so
    changes here must stay in sync with that function.
    """
    path = Path("data\daily_check\csv")
    Path("data\daily_check\csv").mkdir(parents=True, exist_ok=True)

    filename = datetime.now().strftime("%Y%m%d") + f"_{tag}-check.csv"
    filepath = os.path.join(path, filename)
    df.to_csv(filepath, sep='|',index=False)
    print(f'Data saved as table in \{filepath}')