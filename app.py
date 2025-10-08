# app.py
import streamlit as st
from datetime import datetime
import base64
import requests
import gspread
from google.oauth2.service_account import Credentials
from io import BytesIO

st.set_page_config(page_title="My AI Projects Portfolio", layout="wide")

# ---------- CONFIG ----------
# Secrets used (set these in Streamlit Cloud -> Settings -> Secrets)
# st.secrets["ADMIN_PASSWORD"] - string, admin password
# st.secrets["CLOUDINARY"] = {"cloud_name": "...", "api_key": "...", "api_secret": "..."}
# st.secrets["GSHEET"] = {"sheet_id": "your_google_sheet_id", "worksheet_name": "Sheet1"}
# st.secrets["GCP_SERVICE_ACCOUNT"] = <full service account JSON as nested dict> OR as string (works both ways)

CLOUDINARY = st.secrets.get("CLOUDINARY", {})
GSHEET = st.secrets.get("GSHEET", {})
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD")
GCP_SA = st.secrets.get("GCP_SERVICE_ACCOUNT")

if not CLOUDINARY or not GSHEET:
    st.error("App not configured. Please set CLOUDINARY and GSHEET in Streamlit secrets.")
    st.stop()

# ---------- Helpers ----------
def cloudinary_upload(file_bytes: bytes, filename: str):
    """
    Upload file bytes to Cloudinary via unsigned upload.
    Requires CLOUDINARY config in st.secrets.
    Returns secure_url on success.
    """
    cloud = CLOUDINARY
    url = f"https://api.cloudinary.com/v1_1/{cloud['cloud_name']}/auto/upload"
    data = {
        "upload_preset": cloud.get("upload_preset", ""),  # optional if using unsigned preset
        "api_key": cloud.get("api_key")
    }
    files = {"file": (filename, file_bytes)}
    # If you rely on signed uploads you can send timestamp + signature (not included here).
    # Using simple approach with basic auth if api_secret available:
    if cloud.get("api_secret"):
        # Use basic auth
        res = requests.post(url, files=files, data=data, auth=(cloud["api_key"], cloud["api_secret"]))
    else:
        res = requests.post(url, files=files, data=data)
    res.raise_for_status()
    return res.json()["secure_url"]

def open_sheet():
    """Open Google Sheet and return worksheet object."""
    # Service account: can be supplied either as dict (st.secrets) or a JSON string
    sa = GCP_SA
    if isinstance(sa, str):
        import json
        sa = json.loads(sa)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(sa, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GSHEET["sheet_id"])
    ws = sh.worksheet(GSHEET.get("worksheet_name", "Sheet1"))
    return ws

def add_project_to_sheet(title, description, link, media_url, media_type):
    ws = open_sheet()
    now = datetime.utcnow().isoformat()
    # columns: Title | Description | Link | MediaURL | MediaType | CreatedAt
    ws.append_row([title, description, link or "", media_url or "", media_type or "", now])

def read_projects_from_sheet():
    ws = open_sheet()
    rows = ws.get_all_values()
    # assume header row exists
    if not rows or len(rows) < 2:
        return []
    header = rows[0]
    data_rows = rows[1:]
    # map rows to dicts (handles missing columns)
    projects = []
    for r in data_rows:
        d = {header[i]: r[i] if i < len(r) else "" for i in range(len(header))}
        projects.append(d)
    return projects[::-1]  # newest first

# ---------- UI ----------
st.title("AI Projects Portfolio")

tabs = st.tabs(["Portfolio", "Admin (Add project)"])
with tabs[0]:
    st.markdown("### Projects (public view)")
    try:
        projects = read_projects_from_sheet()
    except Exception as e:
        st.warning("Unable to read projects from Google Sheets. If this is the first time, no projects exist yet.")
        projects = []

    if not projects:
        st.info("No projects yet. If you're the owner, add projects from Admin tab.")
    else:
        cols = st.columns(3)
        for i, p in enumerate(projects):
            with cols[i % 3]:
                title = p.get("Title", "Untitled")
                desc = p.get("Description", "")
                link = p.get("Link", "")
                murl = p.get("MediaURL", "")
                mtype = p.get("MediaType", "")
                st.markdown(f"#### {title}")
                st.write(desc)
                if link:
                    st.markdown(f"[Open Demo]({link})")
                if murl:
                    # embed image/video if Cloudinary link or standard url
                    if mtype.startswith("video") or murl.lower().endswith((".mp4", ".webm")):
                        st.video(murl)
                    else:
                        st.image(murl, use_column_width=True)
                st.caption(p.get("CreatedAt", ""))

with tabs[1]:
    st.markdown("### Admin (secure) — add a project")
    # Simple password based admin
    if "admin_logged_in" not in st.session_state:
        st.session_state.admin_logged_in = False

    if not st.session_state.admin_logged_in:
        pwd = st.text_input("Admin password", type="password")
        if st.button("Login"):
            if ADMIN_PASSWORD and pwd == ADMIN_PASSWORD:
                st.session_state.admin_logged_in = True
                st.experimental_rerun()
            else:
                st.error("Wrong password.")
    else:
        st.success("You are logged in as admin.")
        with st.form("add_project_form", clear_on_submit=True):
            title = st.text_input("Project title", max_chars=120)
            desc = st.text_area("Short description")
            link = st.text_input("Demo / Repo link (optional)")
            media = st.file_uploader("Image or video (png/jpg/mp4)", type=["png", "jpg", "jpeg", "mp4"])
            submitted = st.form_submit_button("Add project")

        if submitted:
            if not title:
                st.error("Title is required.")
            else:
                media_url = ""
                media_type = ""
                if media:
                    try:
                        # read bytes and upload to cloudinary
                        bytes_data = media.read()
                        media_type = media.type or ""
                        media_url = cloudinary_upload(bytes_data, media.name)
                        st.success("Uploaded media to Cloudinary.")
                    except Exception as e:
                        st.error(f"Failed to upload media: {e}")
                        media_url = ""

                try:
                    add_project_to_sheet(title, desc, link, media_url, media_type)
                    st.success(f"Project '{title}' added.")
                except Exception as e:
                    st.error(f"Failed to save project metadata: {e}")

        if st.button("Logout"):
            st.session_state.admin_logged_in = False
            st.experimental_rerun()
