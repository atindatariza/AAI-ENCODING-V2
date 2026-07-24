import json
import os
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from PIL import Image
import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="DAR - Gemini AI", layout="wide")
st.title(":memo: DAR Form Scanner - Gemini AI")

# Setup Gemini API
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"] if "GEMINI_API_KEY" in st.secrets else os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# Google Sheets setup
SHEET_ID = "1F1CaSvB7zVaw0fmk_bIUJC1auQ2MvHrgvLBd2kwkP70"


def get_gsheet_client():
    """Connect to Google Sheets using service account credentials."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    return gspread.authorize(creds)


def safe_generate_content(model_name, img, prompt):
    """Generate content using the specified Gemini model."""
    model = genai.GenerativeModel(model_name)
    return model.generate_content([prompt, img])


def extract_encoding_gemini(image):
    """Extract survey form data using Gemini and parse JSON response."""
    prompt = """
    Extract data from this survey form into a JSON list.
    For page 1 "LAS INFORMATION" section upto "OTHER NON MNTHL" and page 2 "LAS PROFILING" upto "REGISTRATION- WITH UPC" section:
    1. Get "LAST NAME AND FIRST NAME" at the column if filled out , extract the handwritten text.
    2. For each column, return the letter of the selected/checked answer. If none, return "".
    3. For "LAS PROFILING" upto "REGISTRATION- WITH UPC" extract the letter or number.
    Return keys like: "LAST NAME", "FIRST NAME", "AGE", "SMOKER", "MALE", "FEMALE", "MB RED", "MB GOLD", "MB CRAFTED RED", "PMKS", "FEB", "FITO", "CHFF", "CHFF XL", "JACKPOT RED", "MORE RED", "WINSTON RED", "WINSTON BLUE", "CAMEL RED", "CAMEL LIGHTS", "MIGHTY RED", "MIGHTY XL", "MARVELS RED", "WINSBORRO RED", "LD RED", "ILLICIT NON MNTL", "OTHER NON MNTL", "MB BLACK MNTL", "MB ICE BLAST MEGA", "MB FUSION PURPLE", "MB CRAFTED ICE", "FTMS", "FT LPE", "FM100B", "CH M100S XL", "CH REMIX", "PM100", "WINSTON EXTREME MINT", "WINSTON PURPLE", "WINSTON MINT BURST MAX", "HOPE MNTL 100s", "HOPE KING SIZE", "MARK", "MIGHTY GREEN", "MIGHTY MAX COOL", "MARVELS GREEN", "JACKPOT GREEN", "LD GREEN", "ILLICIT MENTHOL", "ESSE", "OTHER MNTL", "LAS PROFILING", "FM100s", "FEB", "# OF PACKS", "IF LAS OPEN THE PACK (Y/N)", "VAO (INPUT WHAT VAOs LAS/RT GET)", "GOLDEN TICKET (TARA \"I\" ONLY)", "AMOUNT", "# OF STICKS", "FT LIGHTER", "LOG IN", "NEW REGISTRATION", "REGISTRATION- WITH UPC" etc.
    For handwritten parts in section 1 and 2, use "LAST NAME", "FIRST NAME", "REGISTRATION WITH UPC" for text.
    Only return valid JSON array with 1 object, no other text.
    Example: [{"LAST NAME": "AMORIN", "FIRST NAME": "RANDEL", "AGE": "46", "SMOKER": "/", "MALE": "/,1", "FEMALE": "/,1", "MB RED": "/,1", "REGISTRATION WITH UPC": "FXDHQRZ"}]
    """
    try:
        response = safe_generate_content("gemini-2.5-flash", image, prompt)
    except Exception:
        response = safe_generate_content("gemini-2.5-flash-lite", image, prompt)

    json_text = response.text.strip()
    # Clean markdown code block wraps if present
    if json_text.startswith("```"):
        json_text = json_text.strip("`").replace("json\n", "", 1).strip()

    return json.loads(json_text)


# Initialize session state
if 'df' not in st.session_state:
    st.session_state.df = None

uploaded_file = st.file_uploader("Upload DAR Photo", type=['png', 'jpg', 'jpeg'])

if uploaded_file:
    image = Image.open(uploaded_file)
    st.image(image, caption="Ready to scan", use_container_width=True)

    if st.button(":mag: Run AI Scan", type="primary"):
        with st.spinner('Gemini AI is reading... ~3-5 seconds'):
            try:
                table_data = extract_encoding_gemini(image)
                if table_data:
                    st.success(":white_check_mark: Extracted survey data!")
                    st.session_state.df = pd.DataFrame(table_data)
                else:
                    st.warning("Walang na-detect na data. Try mo mas malinaw na picture.")
            except Exception as e:
                st.error(f"Error: {str(e)}")

# Show editor + sync controls if data exists
if st.session_state.df is not None:
    st.subheader(":clipboard: Verify Data - Edit mo kung may mali")
    
    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        key="editor"
    )
    st.session_state.df = edited_df

    col1, col2 = st.columns(2)
    with col1:
        csv = st.session_state.df.to_csv(index=False).encode('utf-8')
        st.download_button(
            ":inbox_tray: Download CSV",
            csv,
            "dar_data.csv",
            "text/csv",
            use_container_width=True
        )

    with col2:
        if st.button(":rocket: Sync All to Google Sheets", use_container_width=True):
            try:
                with st.spinner('Syncing to Google Sheets...'):
                    client = get_gsheet_client()
                    sheet = client.open_by_key(SHEET_ID).sheet1
                    
                    # Convert DataFrame to clean strings/lists for gspread
                    df_to_sync = st.session_state.df.fillna("")
                    headers = df_to_sync.columns.tolist()
                    rows = df_to_sync.astype(str).values.tolist()

                    existing_records = sheet.get_all_values()
                    
                    if len(existing_records) == 0:
                        # Append both header and rows if spreadsheet is empty
                        sheet.append_rows([headers] + rows, value_input_option='USER_ENTERED')
                    else:
                        # Append only new data rows if headers already exist
                        sheet.append_rows(rows, value_input_option='USER_ENTERED')

                    st.success(f":white_check_mark: {len(rows)} row(s) synced sa Google Sheets!")
                    st.balloons()
            except Exception as e:
                st.error(f"Sync failed: {str(e)}")
                st.code(f"Error details: {repr(e)}")
                st.info("Check: 1. Naka-share ba sheet sa service account? 2. Tama ba secrets?")
else:
    st.info(":point_up_2: Upload a dar photo to start")
    st.warning(":warning: REVIEW and EDIT kung may MALI")
