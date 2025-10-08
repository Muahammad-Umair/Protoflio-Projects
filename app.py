# app.py
import streamlit as st
from datetime import datetime
import base64
import requests
import gspread
from google.oauth2.service_account import Credentials
from io import BytesIO
import json

st.set_page_config(page_title="My AI Projects Portfolio", layout="wide")



# DEBUG block - remove after testing
import streamlit as _st
try:
    present = "ADMIN_PASSWORD" in _st.secrets
    val = _st.secrets.get("ADMIN_PASSWORD")
    if val is None:
        _st.write("ADMIN_PASSWORD present:", present, "| value is None")
    else:
        _st.write("ADMIN_PASSWORD present:", present, "| length:", len(val))
except Exception as e:
    _st.write("Error reading secrets:", e)
# End DEBUG


# ---------- CONFIG ----------
# Secrets used (set these in Streamlit Cloud -> Settings -> Secrets)
# st.secrets["CLOUDINARY"] -> table with keys: cloud_name, api_key, api_secret (optional), upload_preset (optional)
# st.secrets["GSHEET"] -> table with keys: sheet_id, worksheet_name
# st.secrets["GCP_SERVICE_ACCOUNT"] -> triple-quoted JSON string (full service account JSON)
# st.secrets["ADMIN_PASSWORD"] -> admin password string

CLOUDINARY = st.secrets.get("CLOUDINARY", {})
GSHEET = st.secrets.get("GSHEET", {})
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD")
GCP_SA = st.secrets.get("GCP_SERVICE_ACCOUNT")

# Basic config checks
if not CLOUDINARY or not GSHEET:
    st.error("App not configured. Please set CLOUDINARY and GSHEET in Streamlit Secrets.")
    st.stop()

# ---------- Helpers ----------
def cloudinary_upload(file_bytes: bytes, filename: str, timeout=30):
    """
    Upload file bytes to Cloudinary.
    - If CLOUDINARY.upload_preset exists -> unsigned upload.
    - Otherwise if api_secret exists -> signed/basic auth upload.
    Returns secure_url on success.
    Raises RuntimeError on failure with helpful message.
    """
    cloud = CLOUDINARY
    if not cloud.get("cloud_name"):
        raise ValueError("Cloudinary not configured (cloud_name missing in secrets).")

    url = f"https://api.cloudinary.com/v1_1/{cloud['cloud_name']}/auto/upload"
    data = {}
    if cloud.get("upload_preset"):
        data["upload_preset"] = cloud["upload_preset"]
    if cloud.get("api_key"):
        data["api_key"] = cloud["api_key"]

    files = {"file": (filename, file_bytes)}

    try:
        if cloud.get("api_secret"):
            # Signed / auth upload using basic auth
            res = requests.post(url, files=files, data=data, auth=(cloud["api_key"], cloud["api_secret"]), timeout=timeout)
        else:
            # Unsigned upload (requires upload_preset set in Cloudinary console)
            res = requests.post(url, files=files, data=data, timeout=timeout)
        res.raise_for_status()
        payload = res.json()
        # prefer secure_url if present
        return payload.get("secure_url") or payload.get("url") or payload
    except requests.exceptions.RequestException as e:
        # try to provide response body if available for debugging
        body = ""
        try:
            body = e.response.text if e.response is not None else ""
        except Exception:
            body = ""
        raise RuntimeError(f"Cloudinary upload failed: {e}\nResponse body: {body}")

def open_sheet():
    """Open Google Sheet and return worksheet object (with helpful errors)."""
    sa = GCP_SA
    if isinstance(sa, str):
        sa = json.loads(sa)
    sheet_id = GSHEET.get("sheet_id")
    if not sheet_id:
        raise ValueError("GSHEET.sheet_id missing in secrets. Put your Google Sheet ID in GSHEET.sheet_id")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(sa, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
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
    # expect header row present
    if not rows or len(rows) < 2:
        return []
    header = rows[0]
    data_rows = rows[1:]
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
        st.warning("Unable to read projects from Google Sheets. If this is the first time, no projects exist yet or the app is not fully configured.")
        st.info("If you're the owner, go to Admin tab to add projects after configuring Secrets.")
        projects = []

    if not projects:
        st.info("No projects yet. If you're the owner, add projects from the Admin tab.")
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
                    try:
                        if (isinstance(mtype, str) and mtype.startswith("video")) or murl.lower().endswith((".mp4", ".webm")):
                            st.video(murl)
                        else:
                            st.image(murl, use_column_width=True)
                    except Exception:
                        st.write("Media could not be displayed.")
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
            media = st.file_uploader("Image or video (png/jpg/mp4). Keep files small (<= 25 MB).", type=["png", "jpg", "jpeg", "mp4"])
            submitted = st.form_submit_button("Add project")

        if submitted:
            if not title:
                st.error("Title is required.")
            else:
                media_url = ""
                media_type = ""
                if media:
                    # file-like object; check size if available (streamlit InMemoryUploadedFile has .size)
                    try:
                        size_ok = True
                        max_bytes = 25 * 1024 * 1024  # 25 MB
                        if hasattr(media, "size") and media.size:
                            if media.size > max_bytes:
                                size_ok = False
                                st.error("File too large. Please upload files <= 25 MB.")
                        if size_ok:
                            bytes_data = media.read()
                            media_type = media.type or ""
                            try:
                                media_url = cloudinary_upload(bytes_data, media.name)
                                st.success("Uploaded media to Cloudinary.")
                            except Exception as e:
                                st.error(f"Failed to upload media: {e}")
                                media_url = ""
                    except Exception as e:
                        st.error(f"Failed reading uploaded file: {e}")
                        media_url = ""

                try:
                    add_project_to_sheet(title, desc, link, media_url, media_type)
                    st.success(f"Project '{title}' added.")
                except Exception as e:
                    st.error(f"Failed to save project metadata: {e}")

        if st.button("Logout"):
            st.session_state.admin_logged_in = False
            st.experimental_rerun()
