from config import base_url

# Prompt/instruction text keyed by name.
# Only 'refresh_cookies_instruction' is used by the active pipeline
# (helper_functions.update_cookies(), printed before the cURL paste prompt).
dialogues = {
    "refresh_cookies_instruction" : rf"""
Follow the following instructions to refresh cookies:

1. Navigate to {base_url}/login on your browser
2. Open developer tools (Crtl + Shift + I)
3. Go to Network > Fetch/XHR
4. Login with your credentials
5. There should be a new request 'get?url=%2Fhome'under Fetch/XHR. Right click on > Copy > Copy as cURL (cmd)
6. Paste code below
"""
}
