import os
import logging
import shutil
import time
import asyncio  
import subprocess
import stripe
import json
import re
import sys
import math
import base64
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy import text

from dotenv import load_dotenv

# Load environment variables as early as possible so every os.getenv() call
# below (API keys, DB URL, etc.) can see values from a local .env file.
# On platforms like Railway, env vars are injected directly and this is a no-op.
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.responses import RedirectResponse  # <--- ΠΡΟΣΘΕΣΕ ΑΥΤΟ

# --- DATABASE SETUP ---
# --- AI LIBRARIES ---
from google import genai
from google.genai import types
from openai import OpenAI
from datetime import datetime, timedelta
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import Depends, HTTPException, status
import database



# Import από το αρχείο που μόλις φτιάξαμε
import database
from database import User, get_db, Project, ChatMessage
from datetime import timedelta
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import Depends, status

import boto3
from botocore.client import Config
from pydantic import BaseModel
import uuid

# Import τη βάση μας
import database
from database import User, get_db

import imageio_ffmpeg  # <--- ΝΕΟ: Εισάγουμε το imageio-ffmpeg για να βρούμε το ffmpeg path
import secrets
import resend

# --- ΡΥΘΜΙΣΕΙΣ RESEND ---
resend.api_key = os.getenv("RESEND_API_KEY")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://www.vincicutai.com") # Το URL σου για να φτιάχνονται σωστά τα links



# --- Ρυθμίσεις Cloudflare R2 ---
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "vincicut-videos")

# Σύνδεση με το R2
s3_client = boto3.client(
    's3',
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    config=Config(signature_version='s3v4'),
    region_name='auto'
)

# --- SECURITY CONFIGURATION ---
# IMPORTANT: set a long random value in your .env / host env vars.
# Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is not set. See .env.example.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # Το login διαρκεί 7 μέρες

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- SECURITY FUNCTIONS ---

def get_password_hash(password):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception
    return user


app = FastAPI(title="Media Intelligence Agent (Ultimate Edition)")
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    return response

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])







# --- 1. CONFIGURATION ---
# (load_dotenv() already called near the top of the file, before it's needed)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')



def split_long_srt_segments(srt_text, max_words=3):
    """Σπάει τα μεγάλα segments σε μικρότερα των max_words λέξεων."""
    import re
    
    segments = re.split(r'\n\n', srt_text.strip())
    new_srt = []
    global_index = 1
    
    for segment in segments:
        lines = segment.split('\n')
        if len(lines) < 3: continue
        
        index = lines[0]
        time_range = lines[1]
        content = " ".join(lines[2:])
        
        words = content.split()
        if len(words) <= max_words:
            new_srt.append(f"{global_index}\n{time_range}\n{content}")
            global_index += 1
            continue
            
        # Αν έχει πολλές λέξεις, σπάσε το
        start_time_str, end_time_str = time_range.split(' --> ')
        start_total = parse_time_str(start_time_str.replace(',', '.'))
        end_total = parse_time_str(end_time_str.replace(',', '.'))
        duration = end_total - start_total
        
        num_chunks = math.ceil(len(words) / max_words)
        duration_per_chunk = duration / num_chunks
        
        for i in range(num_chunks):
            chunk_words = words[i*max_words : (i+1)*max_words]
            chunk_content = " ".join(chunk_words)
            
            chunk_start = start_total + (i * duration_per_chunk)
            chunk_end = chunk_start + duration_per_chunk
            
            new_time_range = f"{format_timestamp(chunk_start)} --> {format_timestamp(chunk_end)}"
            new_srt.append(f"{global_index}\n{new_time_range.replace('.', ',')}\n{chunk_content.upper()}")
            global_index += 1
            
    return "\n\n".join(new_srt)

def log_msg(msg):
    print(f"👉 {msg}", flush=True)

API_BASE_URL = ""

# 👇 Η ΜΕΓΑΛΗ ΑΛΛΑΓΗ: ΧΡΗΣΙΜΟΠΟΙΟΥΜΕ os.environ ΑΠΕΥΘΕΙΑΣ 👇
# Το os.getenv καμιά φορά επιστρέφει None αν δεν έχει φορτώσει καλά το περιβάλλον.
# Το os.environ[] πετάει λάθος αν λείπει, αλλά στο Railway είναι ο σωστός τρόπος.

google_key = os.getenv("GOOGLE_API_KEY")

openai_key = os.getenv("OPENAI_API_KEY") # Προαιρετικό

# Debugging Log (Θα τυπώσει μόνο τα πρώτα 4 γράμματα για να δούμε αν το βρήκε)
if google_key:
    log_msg(f"✅ GOOGLE KEY FOUND: {google_key[:4]}...******")
else:
    log_msg("❌ CRITICAL: GOOGLE_API_KEY IS STILL MISSING OR EMPTY")

if not google_key: log_msg("⚠️ WARNING: GOOGLE_API_KEY not found in .env")

client_google = genai.Client(api_key=google_key)
client_openai = OpenAI(api_key=openai_key) if openai_key else None

stripe.api_key = os.getenv("STRIPE_API_KEY") # <--- ΑΥΤΟ ΕΙΝΑΙ ΤΟ STRIPE KEY

# --- 2. APP SETUP ---


# --- PATH CONFIGURATION (RUNPOD READY) ---
# Ελέγχουμε αν υπάρχει ο φάκελος /workspace (RunPod Permanent Storage)
# Αν υπάρχει, χρησιμοποιούμε αυτόν. Αν όχι, τον τρέχοντα φάκελο (Local).
BASE_DIR = "/workspace" if os.path.exists("/workspace") else "."

OUTPUT_DIR = os.path.join(BASE_DIR, "generated_shorts")
if not os.path.exists(OUTPUT_DIR): 
    os.makedirs(OUTPUT_DIR)

# Mount τον φάκελο για να είναι προσβάσιμος από το web
app.mount("/generated_shorts", StaticFiles(directory=OUTPUT_DIR), name="generated_shorts")
app.mount("/static", StaticFiles(directory=".", html=True), name="static")

log_msg(f"📂 Storage Path configured at: {OUTPUT_DIR}")

active_video_session = {
    "chat_session": None, 
    "last_video_path": None,
    "current_mode": "custom",  # <-- ΝΕΟ
    "clips_data": []           # <-- ΝΕΟ
}
executor = ThreadPoolExecutor(max_workers=7)

# --- HELPER FUNCTIONS ---

# Μετατροπή δευτερολέπτων σε μορφή SRT (00:00:00,000)
def format_timestamp(seconds):
    hours = math.floor(seconds / 3600)
    seconds %= 3600
    minutes = math.floor(seconds / 60)
    seconds %= 60
    milliseconds = round((seconds - math.floor(seconds)) * 1000)
    seconds = math.floor(seconds)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

# Δημιουργία αρχείου SRT από το Whisper
# Δημιουργία "Smart" SRT (Λίγες λέξεις τη φορά)
def generate_srt(audio_path, srt_path, is_viral=False):
    if not client_openai: 
        log_msg("⚠️ OpenAI API Key missing. Cannot generate subtitles.")
        return False
        
    # 1. Φτιάχνουμε όνομα για το προσωρινό μικρό αρχείο
    temp_audio = f"temp_audio_{int(time.time())}.mp3"

    try:
        log_msg("🎙️ Compressing audio for Whisper (32k)...")
        
        # 2. ΣΥΜΠΙΕΣΗ: Βγάζουμε μόνο τον ήχο και τον μικραίνουμε πολύ (32k bitrate)
        # Αυτό κάνει το αρχείο από 26MB -> ~1MB για να περνάει στο OpenAI
        cmd = [
            get_ffmpeg_command(), "-y",
            "-i", audio_path, 
            "-vn",              # Όχι εικόνα
            "-acodec", "libmp3lame", 
            "-b:a", "32k",      # Πολύ μικρό bitrate
            temp_audio
        ]
        
        # Τρέχουμε την εντολή
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=creation_flags)

        # 3. ΑΠΟΣΤΟΛΗ: Στέλνουμε το ΜΙΚΡΟ αρχείο (temp_audio)
        log_msg(f"🚀 Sending compressed audio to OpenAI...")

        # Προσθέτουμε αυτό το prompt για να "συμμαζέψουμε" το Whisper
        whisper_prompt = "Keep segments very short, max 3-4 words per line. Use the original language of the video. No translation."
        
        with open(temp_audio, "rb") as audio_file:
           transcript = client_openai.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file, 
                response_format="verbose_json",        # <--- ΑΛΛΑΓΗ: Ζητάμε αναλυτικό JSON
                timestamp_granularities=["word"],      # <--- ΝΕΟ: Ζητάμε ακρίβεια ανά λέξη
                language="en" 
            )
            
        # 4. Αποθήκευση
       # 4. Αποθήκευση
        words = transcript.words
        new_srt = []
        global_index = 1
       
        if is_viral:
           # --- ΝΕΑ ΛΟΓΙΚΗ ΓΙΑ VIRAL (Κόβει στις παύσεις) ---
           max_words = 2 # Μέχρι 2 λέξεις
           max_gap = 0.4 # Αν η επόμενη λέξη αργήσει πάνω από 0.4 δευτ., κόβει τον υπότιτλο!
           current_chunk = []
           
           for w in words:
               if not current_chunk:
                   current_chunk.append(w)
               else:
                   prev_w = current_chunk[-1]
                   gap = w.start - prev_w.end
                   
                   if len(current_chunk) >= max_words or gap > max_gap:
                       start_time = current_chunk[0].start
                       end_time = current_chunk[-1].end
                       text = " ".join([cw.word.strip() for cw in current_chunk]).upper()
                       time_range = f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}"
                       new_srt.append(f"{global_index}\n{time_range.replace('.', ',')}\n{text}")
                       global_index += 1
                       current_chunk = [w]
                   else:
                       current_chunk.append(w)
           
           if current_chunk:
               start_time = current_chunk[0].start
               end_time = current_chunk[-1].end
               text = " ".join([cw.word.strip() for cw in current_chunk]).upper()
               time_range = f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}"
               new_srt.append(f"{global_index}\n{time_range.replace('.', ',')}\n{text}")
        else:
           # --- ΠΑΛΙΑ ΣΟΥ ΛΟΓΙΚΗ ΓΙΑ MOVIE (Μένει άθικτη) ---
           for i in range(0, len(words), 3): 
               chunk = words[i:i + 3]
               if not chunk: continue
               
               start_time = chunk[0].start
               end_time = chunk[-1].end
               text = " ".join([w.word.strip() for w in chunk]).upper()
               
               time_range = f"{format_timestamp(start_time)} --> {format_timestamp(end_time)}"
               new_srt.append(f"{global_index}\n{time_range.replace('.', ',')}\n{text}")
               global_index += 1

        with open(srt_path, "w", encoding="utf-8") as srt:
            srt.write("\n\n".join(new_srt))

        log_msg("✅ Subtitles generated via Cloud API!")
        
        # 5. Καθαρισμός του temp αρχείου
        if os.path.exists(temp_audio):
            os.remove(temp_audio)
            
        return True
        
    except Exception as e:
        log_msg(f"❌ OpenAI Whisper API Error: {e}")
        # Καθαρισμός αν γίνει λάθος
        if os.path.exists(temp_audio):
            os.remove(temp_audio)
        return False
    
def parse_time_str(time_str):
    try:
        clean_time = str(time_str).replace(',', '.').strip()
        parts = clean_time.split(':')
        if len(parts) > 3: parts = parts[:3]
        if len(parts) == 2: return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3: return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return 0
    except: return 0

def get_video_metadata(file_path):
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=creation_flags)
        data = json.loads(result.stdout)
        video_stream = next((s for s in data['streams'] if s['codec_type'] == 'video'), None)
        if not video_stream: return {"fps": 30.0, "duration": 0}
        
        r_frame_rate = video_stream.get('r_frame_rate', '30/1')
        if '/' in r_frame_rate:
            num, den = map(int, r_frame_rate.split('/'))
            fps = num / den
        else:
            fps = float(r_frame_rate)
        return {"fps": fps, "duration": float(data['format']['duration'])}
    except: return {"fps": 30.0, "duration": 0}

def get_ffmpeg_command():
    # Επιστρέφουμε σκέτο "ffmpeg" για να πάρει αυτό του συστήματος (Railway)
    # που έχει υποστήριξη για γραμματοσειρές
    return "ffmpeg"

def compress_video_sync(input_path, output_path):
    log_msg("🚀 Compressing for AI (360p / Ultrafast)...")
    try:
        cmd = [get_ffmpeg_command(), "-y", "-i", input_path, "-vf", "scale=-2:360", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-c:a", "aac", "-ac", "1", output_path]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=creation_flags)
        return True
    except: return False

def create_viral_short_sync(input_path, start_time, end_time, output_filename):
    # Old function - kept for compatibility but not used
    return None 

# 👇 Η ΝΕΑ ΠΛΗΡΗΣ ΣΥΝΑΡΤΗΣΗ ΜΕ ΤΑ 2 ΣΤΥΛ ΥΠΟΤΙΤΛΩΝ 👇
def create_pro_short_sync(input_path, start_time, end_time, output_path, style="clean"):
    """
    Styles: 'clean', 'viral', 'vertical', 'square', 'square_subs', 'subs', 'audio'
    """
    duration = end_time - start_time
    ffmpeg_cmd = get_ffmpeg_command()
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fonts_dir_arg = base_dir.replace("\\", "/") if os.name == 'nt' else base_dir

    try:
        files_in_dir = os.listdir(base_dir)
        if "font.ttf" in files_in_dir:
            log_msg(f"✅ CONFIRMED: 'font.ttf' found in {base_dir}")
        else:
            log_msg(f"❌ CRITICAL: 'font.ttf' NOT FOUND. Found: {files_in_dir}")
    except Exception as e:
        log_msg(f"⚠️ Error checking directory: {e}")

    log_msg(f"🎬 Processing Style: {style.upper()} | Duration: {duration}s")

    # 👇 ΣΤΥΛ ΧΩΡΙΣ ΟΝΟΜΑ (Παίρνει αυτόματα το font.ttf) 👇
    sub_style_viral = (
        "FontSize=17,PrimaryColour=&H00FFFF,OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=70,Bold=1,"
        "MaxLineLen=20" # <--- Αυτό θα σπάει τις μεγάλες προτάσεις σε 2-3 λέξεις!
    )

    sub_style_movie = (
        "FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=1,Shadow=1,Alignment=2,MarginV=30,Bold=0"
    )

    # --- ΕΠΕΞΕΡΓΑΣΙΑ ---

    # 1. AUDIO EXTRACT (MP3)
    if style == "audio":
        mp3_output = output_path.rsplit('.', 1)[0] + ".mp3"
        cmd = [
            ffmpeg_cmd, "-y", "-ss", str(start_time), "-t", str(duration),
            "-i", input_path, "-vn", "-acodec", "libmp3lame", "-q:a", "2", mp3_output
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=creation_flags)
            return mp3_output
        except Exception as e:
            log_msg(f"❌ Audio Error: {e}")
            return False

    # 2. SQUARE VIDEO (1:1 - No Subs)
    if style == "square":
        cmd = [
            ffmpeg_cmd, "-y", "-ss", str(start_time), "-t", str(duration),
            "-i", input_path,
            "-vf", "crop='min(iw,ih)':'min(iw,ih)'", 
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", output_path
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=creation_flags)
            return output_path
        except: return False

    # 3. SQUARE + SUBS (1:1 + Viral Subs)
    if style == "square_subs":
        srt_file = output_path.replace(".mp4", ".srt")
        log_msg("🎙️ Generating Subtitles for Square Video...")
        
        has_subs = generate_srt(input_path, srt_file, is_viral=True) # Βγάζει subs από το αρχικό
        
        if has_subs and os.path.exists(srt_file):
            srt_esc = srt_file.replace("\\", "/").replace(":", "\\:")
            # Χρήση VIRAL STYLE
            video_filters = f"crop='min(iw,ih)':'min(iw,ih)',subtitles={srt_esc}:force_style='{sub_style_viral}'"
            
            cmd = [
                ffmpeg_cmd, "-y", "-ss", str(start_time), "-t", str(duration),
                "-i", input_path, "-vf", video_filters, 
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", output_path
            ]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=creation_flags)
                try: os.remove(srt_file)
                except: pass
                return output_path
            except: return False
        else:
            style = "square" # Fallback

    # 4. VERTICAL CLEAN (9:16 No Subs)
    if style == "vertical":
        filter_complex = "[0:v]split=2[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg_blurred];[fg]scale=1080:-1[fg_scaled];[bg_blurred][fg_scaled]overlay=(W-w)/2:(H-h)/2"
        cmd = [
            ffmpeg_cmd, "-y", "-ss", str(start_time), "-t", str(duration),
            "-i", input_path, "-vf", filter_complex,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", output_path
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=creation_flags)
            return output_path
        except: return False

    # 5. VIRAL (9:16 + Viral Subs)
    if style == "viral":
        temp_video = output_path.replace(".mp4", "_temp.mp4")
        srt_file = output_path.replace(".mp4", ".srt")
        
        # Filter για κόψιμο και θόλωμα
        filter_complex = "[0:v]split=2[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:10[bg_blurred];[fg]scale=1080:-1[fg_scaled];[bg_blurred][fg_scaled]overlay=(W-w)/2:(H-h)/2"
        
        cmd_cut = [ffmpeg_cmd, "-y", "-ss", str(start_time), "-t", str(duration), "-i", input_path, "-vf", filter_complex, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", "-c:a", "aac", "-b:a", "192k", temp_video]
        
        try:
            # Βήμα 1: Δημιουργία του κάθετου βίντεο
            subprocess.run(cmd_cut, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=creation_flags)
            
            log_msg("🎙️ Generating Subtitles...")
            has_subs = generate_srt(temp_video, srt_file, is_viral=True)
            
            if has_subs and os.path.exists(srt_file):
                # --- ΔΙΟΡΘΩΣΗ ΜΕΤΑΒΛΗΤΩΝ ΚΑΙ PATHS ---
                abs_srt = os.path.abspath(srt_file).replace("\\", "/")
                if os.name == 'nt':
                    abs_srt = abs_srt.replace(":", "\\:")
                
                # 👇 ΑΥΤΟ ΕΛΕΙΠΕ ΚΑΙ ΕΣΚΑΓΕ ΤΟ SERVER (Error 500) 👇
                abs_srt_escaped = abs_srt 

                log_msg(f"🔥 Burning Viral Subs from: {abs_srt_escaped}")

                abs_srt = os.path.abspath(srt_file).replace("\\", "/")
                abs_srt_ffmpeg = abs_srt.replace(":", "\\:")
                
                # 👇 ΠΡΟΣΘΕΣΑΜΕ ΤΟ fontsdir='.' ΓΙΑ ΝΑ ΒΡΕΙ ΤΟ ROBOTO FONT 👇
                cmd_burn = [
                    ffmpeg_cmd, "-y", "-i", temp_video, 
                    # 1. Βάζουμε το φίλτρο
                    "-vf", f"subtitles='{abs_srt_ffmpeg}':force_style='{sub_style_viral}'",
                    
                    # 2. ΑΥΤΟ ΕΛΕΙΠΕ! Χωρίς αυτό, δεν κάνει Render!
                    "-c:v", "libx264", 
                    "-preset", "ultrafast", 
                    "-crf", "23",
                    
                    # 3. Ο ήχος αντιγραφή
                    "-c:a", "copy", 
                    output_path
                ]
                
                # Εκτέλεση με καταγραφή λάθους
                result = subprocess.run(cmd_burn, capture_output=True, text=True, creationflags=creation_flags)
                
                if result.returncode != 0:
                    log_msg(f"❌ FFmpeg Viral Error:\n{result.stderr}")
                    # Αν αποτύχει, σώσε το βίντεο σκέτο
                    shutil.move(temp_video, output_path)
                else:
                    try: os.remove(temp_video); os.remove(srt_file)
                    except: pass
                
                return output_path
            else:
                # Αν δεν βρέθηκαν υπότιτλοι
                shutil.move(temp_video, output_path)
                return output_path

        except Exception as e:
            log_msg(f"❌ CRITICAL PYTHON ERROR in VIRAL: {e}")
            return False

    # 6. DEFAULT SUBS (Original Aspect + Yellow Viral Subs) 
    if style == "subs":
        srt_file = output_path.replace(".mp4", ".srt")
        log_msg("🎙️ Generating Default Yellow Subtitles...")
        
        # 👇 ΚΑΝΑΜΕ is_viral=True ΓΙΑ ΝΑ ΣΠΑΕΙ ΤΙΣ ΛΕΞΕΙΣ (TikTok ρυθμός)
        has_subs = generate_srt(input_path, srt_file, is_viral=True)
        
        if has_subs and os.path.exists(srt_file):
                abs_srt = os.path.abspath(srt_file).replace("\\", "/")
                abs_srt_ffmpeg = abs_srt.replace(":", "\\:")
                
                log_msg(f"🔥 Burning Default Yellow Subs from: {abs_srt}")
                
                # 👇 ΕΔΩ ΒΑΖΟΥΜΕ ΤΟ VIRAL STYLE (Κίτρινα, μεγάλα γράμματα)
                video_filter = f"subtitles={abs_srt_ffmpeg}:force_style='{sub_style_viral}'"

                cmd_burn = [
                    ffmpeg_cmd, "-y",
                    "-ss", str(start_time), "-t", str(duration),
                    "-i", input_path,
                    "-vf", video_filter, 
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "192k",
                    output_path
                ]
                
                result = subprocess.run(cmd_burn, capture_output=True, text=True, creationflags=creation_flags)
                
                if result.returncode != 0:
                    log_msg(f"❌ FFmpeg Subs Error:\n{result.stderr}")
                    shutil.copy(input_path, output_path)
                else:
                    try: os.remove(srt_file)
                    except: pass
                
                return output_path

    # 6B. MOVIE SUBS (Original Aspect + Cinematic White Subs) - ΜΟΝΟ ΑΝ ΖΗΤΗΘΕΙ
    if style == "movie_subs":
        srt_file = output_path.replace(".mp4", ".srt")
        log_msg("🎙️ Generating Cinematic White Subtitles...")
        
        # 👇 is_viral=False για να βγάζει μεγάλες προτάσεις 
        has_subs = generate_srt(input_path, srt_file, is_viral=False)
        
        if has_subs and os.path.exists(srt_file):
                abs_srt = os.path.abspath(srt_file).replace("\\", "/")
                abs_srt_ffmpeg = abs_srt.replace(":", "\\:")
                
                log_msg(f"🔥 Burning Movie Subs from: {abs_srt}")
                
                # 👇 ΕΔΩ ΒΑΖΟΥΜΕ ΤΟ MOVIE STYLE (Λευκά, απλά γράμματα)
                video_filter = f"subtitles={abs_srt_ffmpeg}:force_style='{sub_style_movie}'"

                cmd_burn = [
                    ffmpeg_cmd, "-y",
                    "-ss", str(start_time), "-t", str(duration),
                    "-i", input_path,                            
                    "-vf", video_filter, 
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23", 
                    "-c:a", "aac", "-b:a", "192k",
                    output_path
                ]
                
                result = subprocess.run(cmd_burn, capture_output=True, text=True, creationflags=creation_flags)
                
                if result.returncode != 0:
                    log_msg(f"❌ FFmpeg Movie Subs Error:\n{result.stderr}")
                    shutil.copy(input_path, output_path)
                else:
                    try: os.remove(srt_file)
                    except: pass
                
                return output_path
    
    
    # --- 8. GIF MAKER ---
    if style == "gif":
        gif_output = output_path.rsplit('.', 1)[0] + ".gif"
        # Φίλτρο για καλή ποιότητα GIF
        vf = "fps=15,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
        cmd = [ffmpeg_cmd, "-y", "-ss", str(start_time), "-t", str(duration), "-i", input_path, "-vf", vf, gif_output]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=creation_flags)
            return gif_output
        except: return False

    # --- 9. SCREENSHOT / THUMBNAIL (FINAL FIX) ---
    if style == "screenshot":
        # 1. Διόρθωση ονόματος αρχείου
        img_output = output_path
        if output_path.endswith(".mp4"):
            img_output = output_path.replace(".mp4", ".jpg")
        elif not output_path.endswith(".jpg"):
            img_output = output_path + ".jpg"

        # 2. Η ΤΕΛΙΚΗ ΕΝΤΟΛΗ (Με -an και -f image2)
        cmd = [
            ffmpeg_cmd, "-y",
            "-ss", str(start_time), # Το -ss μπαίνει ΠΡΙΝ το input για να μην σκάει το FFmpeg
            "-i", input_path,       
            "-vframes", "1",        
            "-q:v", "2",            
            # ΣΒΗΣΑΜΕ το "-update", "1", γιατί προκαλεί corrupt στα JPEGs
            img_output
        ]
        try:
            # Capture output για να δούμε αν σκάσει
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=creation_flags)
            return img_output
        except subprocess.CalledProcessError as e:
            # Τώρα θα δεις στο τερματικό ΓΙΑΤΙ απέτυχε
            log_msg(f"❌ Screenshot Failed Log: {e.stderr.decode('utf-8', errors='ignore')}")
            return False
        except Exception as e:
            log_msg(f"❌ General Error: {e}")
            return False

    # --- 10. MUTED VIDEO (No Audio) ---
    if style == "mute":
        cmd = [
            ffmpeg_cmd, "-y", "-ss", str(start_time), "-t", str(duration),
            "-i", input_path, "-an", # <--- Το -an αφαιρεί τον ήχο
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", output_path
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=creation_flags)
            return output_path
        except: return False

    # 7. CLEAN / DEFAULT
    cmd = [
        ffmpeg_cmd, "-y", "-ss", str(start_time), "-t", str(duration),
        "-i", input_path, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k", output_path
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=creation_flags)
        return output_path
    except: return False

class ChatRequest(BaseModel):
    question: str
    history: List[dict] = []
    image_base64: Optional[str] = None 
    project_id: Optional[int] = None

class ClipRequest(BaseModel):
    start_time: str
    end_time: str
    index: int = 1

    
import base64 # <--- Βεβαιώσου ότι έχεις κάνει import base64 στην αρχή του αρχείου

@app.post("/chat/help")
async def chat_resolve_help(
    req: ChatRequest, 
    current_user: User = Depends(get_current_user), # <--- ΝΕΟ: Login Check
    db: Session = Depends(get_db)                   # <--- ΝΕΟ: Database
):
    # 👇 1. ΕΛΕΓΧΟΣ: Αν δεν έχει credits, κόψτον
    if current_user.credits <= 0:
        raise HTTPException(status_code=403, detail="You have run out of credits. Please upgrade your plan.")

    # --- 👇 1. CODE INJECTION: ΒΡΕΣ Η ΦΤΙΑΞΕ ΤΟ CHAT ---
    project = None
    if req.project_id:
        project = db.query(Project).filter(Project.id == req.project_id, Project.user_id == current_user.id).first()

    if not project:
        # Φτιάχνουμε τίτλο από τις πρώτες λέξεις
        title = "Chat: " + (req.question[:20] + "..." if len(req.question) > 20 else req.question)
        project = Project(
            user_id=current_user.id,
            filename=title,
            status="completed",
            mode="chat",       # <--- Σημαντικό: mode chat
            history_json="[]"  # Αρχικά κενό
        )
        db.add(project)
        db.commit()
        db.refresh(project)
    # 1. Οδηγίες για τον ρόλο του (System Prompt)
    system_instr = (
        "You are a Senior DaVinci Resolve Expert and Tutor."
        "\n\nCONTEXT:"
        "\nThe user will start by telling you if they are a BEGINNER or an EXPERT. You must adapt your style accordingly."
        "\n\n🛑 IF USER IS A BEGINNER:"
        "\n- Explain step-by-step like a tutorial."
        "\n- Describe WHERE buttons are (e.g., 'bottom center of the screen', 'top right inspector')."
        "\n- Avoid keyboard shortcuts unless you explain them."
        "\n- Use emojis to guide them (👉, 🖱️, ⚙️)."
        "\n- Example: 'First, go to the Color Page (rocket icon at the bottom). Then look for the Lift Wheel on the left...'"
        "\n\n🚀 IF USER IS AN EXPERT:"
        "\n- Be concise, direct, and technical."
        "\n- Use standard terminology and shortcuts."
        "\n- Skip UI navigation details."
        "\n\nGENERAL RULES:"
        "\n- When analyzing a Node Graph image, look closely at connections."
        "\n- Always be helpful and polite."
    )

    # 2. Προετοιμασία Ιστορικού (Memory)
    # Το Gemini θέλει το ιστορικό σε συγκεκριμένη μορφή (contents list)
    gemini_history = []
    
    # Προσθήκη παλιών μηνυμάτων
    for msg in req.history:
        role = "user" if msg["sender"] == "user" else "model"
        # Στο ιστορικό κρατάμε μόνο το κείμενο για οικονομία, εκτός αν θες να στέλνεις όλες τις παλιές φώτο (βαραίνει)
        gemini_history.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["text"])]))

    # 3. Προετοιμασία Τρέχοντος Μηνύματος (Current Turn)
    current_parts = []
    
    # Α. Αν υπάρχει εικόνα, την βάζουμε πρώτη
    if req.image_base64:
        try:
            # Αφαιρούμε το header "data:image/jpeg;base64," αν υπάρχει
            image_data = req.image_base64.split(",")[-1] 
            image_bytes = base64.b64decode(image_data)
            
            # Την προσθέτουμε στα parts του μηνύματος
            current_parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
            log_msg("📸 Image attached to chat request.")
        except Exception as e:
            log_msg(f"⚠️ Image decode error: {e}")

    # Β. Προσθέτουμε το κείμενο της ερώτησης
    current_parts.append(types.Part.from_text(text=req.question))
    
    # Προσθήκη του τρέχοντος μηνύματος στη λίστα
    gemini_history.append(types.Content(role="user", parts=current_parts))

    try:
        # 4. Κλήση στο Gemini 2.0 Flash
        # Χρησιμοποιούμε generate_content (stateless) αλλά του δίνουμε όλο το ιστορικό (full context)
        response = client_google.models.generate_content(
            model="gemini-2.5-flash",
            contents=gemini_history,
            config=types.GenerateContentConfig(
                system_instruction=system_instr,
                temperature=0.4 # Χαμηλό temperature για να είναι τεχνικά ακριβής
            )
        )
        
        # --- 👇 2. CODE INJECTION: ΑΠΟΘΗΚΕΥΣΗ ΙΣΤΟΡΙΚΟΥ ---
        ai_answer = response.text
        
        # Φορτώνουμε το παλιό ιστορικό από τη βάση
        current_db_history = json.loads(project.history_json) if project.history_json else []
        
        # Προσθέτουμε την ερώτηση και την απάντηση
        current_db_history.append({"sender": "user", "text": req.question})
        current_db_history.append({"sender": "bot", "text": ai_answer})
        
        # Σώζουμε στη βάση
        # 👇 2. ΧΡΕΩΣΗ: Αν ανέβασε εικόνα, του κόβουμε 1 credit
        if req.image_base64 and current_user.credits > 0:
            current_user.credits -= 1
            
        # Σώζουμε στη βάση
        project.history_json = json.dumps(current_db_history)
        db.commit()

        # Επιστρέφουμε την απάντηση, το ID ΚΑΙ το νέο υπόλοιπο credits
        return {
            "answer": ai_answer, 
            "project_id": project.id,
            "credits_left": current_user.credits
        }
        
    except Exception as e:
        log_msg(f"❌ Chat Error: {e}")
        raise HTTPException(500, f"AI Error: {str(e)}")

# --- ΝΕΟ: ΕΙΔΙΚΟ ENDPOINT ΓΙΑ COLOR GRADING ---
class ColorGradeRequest(BaseModel):
    image_base64: str
    style: str
    is_log: bool = False               
    camera_profile: Optional[str] = "" 

@app.post("/api/color-grade")
async def generate_color_grade(
    req: ColorGradeRequest, 
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Διορθωμένος έλεγχος για 2 credits!
    if current_user.credits < 2:
        raise HTTPException(status_code=403, detail="Not enough credits. 2 credits required.")
    
    # 3. ΤΟ ΚΛΕΙΣΙΜΟ (Το JSON Format)
    json_format = (
        "\n\nOUTPUT FORMAT: strictly valid JSON. Do not include markdown formatting or extra text."
        "{\n"
        "  \"color_grade\": {\n"
        "    \"advice\": \"A professional 1-sentence explanation focusing on why these specific choices were made.\",\n"
        "    \"cdl\": {\n"
        "      \"slope\": {\"R\": 1.00, \"G\": 1.00, \"B\": 1.00},\n"
        "      \"offset\": {\"R\": 0.00, \"G\": 0.00, \"B\": 0.00},\n"
        "      \"power\": {\"R\": 1.00, \"G\": 1.00, \"B\": 1.00},\n"
        "      \"saturation\": 1.00\n"
        "    },\n"
        "    \"sliders\": {\"contrast\": 1.00, \"temperature\": 0},\n"
        "    \"color_slice\": {\"Den\": 0.00, \"Sat\": 1.00, \"Hue\": 0.00}\n"
        "  }\n"
        "}"
    )

    # =========================================================
    # --- ΑΠΟ ΕΔΩ ΞΕΚΙΝΑΕΙ ΤΟ ΝΕΟ DYNAMIC PROMPT ROUTING ---
    # =========================================================
    if not req.is_log:
        # 1. Ο ΚΟΡΜΟΣ (Ισχύει για όλα τα στυλ)
        base_prompt = (
            "You are a Senior DaVinci Resolve Colorist with 20 years of experience in Hollywood DI suites. "
            "Your output is used to generate ASC CDL (Color Decision List) files along with manual finishing touches. "
            "\n\nTECHNICAL RULES FOR VALUES:"
            "1. CDL SOP (SLOPE, OFFSET, POWER) & COLOR WEIGHT: "
            " - SLOPE (Acts like Gain): Default 1.00. WIDER RANGE for noticeable impact on Rec709: 0.75 to 1.30. Use this to aggressively push colors into highlights or pull them out. "
            " - POWER (Acts like Gamma): Default 1.00. WIDER RANGE: 0.75 to 1.30. CRITICAL MATH RULE: To DARKEN midtones, Power must be GREATER than 1.00 (e.g., 1.10 to 1.30). To BRIGHTEN midtones, Power must be LESS than 1.00 (e.g., 0.75 to 0.90). "
            " - OFFSET (Acts like Lift): Default 0.00. Keep strictly between -0.08 and +0.08. Do NOT exceed these limits because Offset globally washes out blacks. "
            " - WEIGHT HIERARCHY: Push Slope and Power further away from 1.00 to create a strong, noticeable 'Wow' factor in the base CDL. Do not be overly conservative with Slope and Power, the CDL must establish 80% of the visual look on its own. Offset is a global bulldozer; even a small +0.02 Blue in Offset will infect the entire image. Never let a cool Offset fight a warm Power—the cool Offset will always win."
            "2. 🟢 THE GREEN CHANNEL RATIO RULE (CRITICAL): AI models often ruin images by over-pushing Green. You CAN use Green, but it MUST always be the 'Supporting Actor', never the lead. "
            " - FOR TEAL/COOL SHADOWS (Offset): Blue must be the primary driver. You may add Green to create Teal, but Green MUST be strictly HALF of Blue or less (e.g., if Blue is +0.03, Green is +0.01 max). Never let Green equal or exceed Blue in the shadows. "
            " - FOR WARM/GOLDEN HIGHLIGHTS (Slope/Power): To create golden warmth (Yellow/Orange), Red must be the highest (e.g., 1.06). You MUST elevate Green slightly to create yellow/gold instead of pink/magenta (e.g., 1.02), but Green MUST always remain significantly lower than Red. Blue is the lowest."
            "3. CDL SATURATION (Scale 0.00 to 4.00): Default is 1.00."
            "- For subtle desaturation use 0.90 to 0.97. "
            "- For a noticeable vibrant punch, use 1.10 to 1.20 ."
            "- For EXTREME, heavy color density on flat images, push it between 1.20 and 1.35 "
            "DYNAMIC CALCULATION: If the original image is extremely dull or flat, push saturation aggressively (1.19+). If the image already has intense native colors, keep it moderate (1.05 to 1.10) to avoid breaking the pixels."
            "4. TEMPERATURE (Sliders): In DaVinci Resolve, Temp ranges from -4000 to +4000. Do not be afraid to use larger numbers (e.g., up to +/-1000 MAX). Subtle shifts are +/- 150 to 300. Strong stylistic moods require +/- 500 to +1000. "
            "5. CONTRAST DYNAMIC SCALING: Evaluate the specific lighting and dynamic range of the provided image to calculate the precise Contrast value needed (Range: 0.85 to 1.25). If the image is flat, calculate the exact boost required to make it punchy. If it has harsh shadows, calculate the exact reduction to soften it. Pick the mathematically optimal value for this specific scenario."
            "6. DENSITY DYNAMIC SCALING (Color Slice): Analyze the image to determine the exact 'Den' (Density) required, using a flexible range from -0.15 to +0.25. If the image is washed out and needs heavy filmic colors, calculate a higher positive Den. If the blacks are already crushing or the image is being deeply darkened by other tools, use negative Den (e.g., -0.05 to -0.15) to keep highlights airy and prevent muddy shadows. 'Sat' is 1.00 default; use between 1.05 to 1.30 for targeted vibrance. 'Hue' MUST be 0.00."
            "\n\nIMAGE ANALYSIS STEPS:"
            "- Step A: Identify lighting and color casts."
            "- Step B: SUBJECT-AWARE GRADING. Identify the Main Subject (e.g., human faces, buildings). Protect and enhance the subject (e.g., keep skin naturally warm). Push stylized colors ONLY subtly into the Offset, ensuring it doesn't bleed into the main subject."
        )

        # 2. ΤΑ ΕΙΔΙΚΑ ΣΤΥΛ (Επιλέγεται ένα από αυτά)
        style_overrides = {
            "Cinematic": (
                "\n\n7. 🎬 STYLE OVERRIDE: CINEMATIC (AGGRESSIVE TEAL & ORANGE): Your goal is a heavy, commercial blockbuster look with extreme color separation. "
                "Analyze the image's existing light and color saturation, then dynamically choose your values to achieve this look. The duller the original image, the harder you must push the math. "
                "- SLOPE (Highlights/Warmth): Push Red high (Range: 1.9 to 1.36) and aggressively pull Blue down (Range: 0.72 to 0.95). To avoid a greenish tint, make sure Green stays balanced between Red and Blue to create clean golden light. "
                "- OFFSET (Shadows/Teal): Push Blue into the positive (Range: +0.02 to +0.08). To carve out the shadows, pull Red negative (Range: -0.02 to -0.06). "
                "CRITICAL GREEN WARNING: Do NOT let the shadows turn muddy green. Green in Offset must always be strictly lower than Blue, or left at 0.00. "
                "- POWER (Midtones): Use Power to anchor the image. If you push Slope extremely high, you must lower Power (e.g., 0.85 to 0.95) to retain contrast and density. "
                "TEMPERATURE: Keep global Temp subtle (+90 to +350 for day, -100 to -300 for night). Let the CDL do the heavy lifting for the cinematic color separation."
            ),
            "Warm": (
                "\n\n7. ☀️ STYLE OVERRIDE: WARM (CRITICAL): Create a golden, glowing image. "
                "Warmth MUST dominate the SLOPE and OFFSET. Do NOT use cool/blue Offsets. "
                "CRITICAL TEMPERATURE RULE: You MUST dynamically evaluate the image's EXISTING warmth and saturation before setting the Temp slider. "
                "- IF the image is ALREADY warm, golden, or highly saturated: Keep Temp adjustments very subtle (+120 to +320) to avoid an unnatural, radioactive orange look. "
                "- IF the image is cold, cloudy, or neutral: You must use higher positive Temperature values (+400 to +850) to heat it up globally. "
                "Lower Contrast slightly (0.91-0.95) if you want a softer feel."
            ),
            "Cold": (
                "\n\n7. ❄️ STYLE OVERRIDE: COLD (CRITICAL): Create a chilly, blue/cyan aesthetic. "
                "Drop the Temperature heavily into the negatives (e.g., -400 to -800). Use Blue in the Offset to cool the shadows and lower Red in the Slope. Do not use warm highlights."
            ),
            "Dark": (
                "\n\n7. 🌑 STYLE OVERRIDE: DARK (CRITICAL): You must fundamentally change how you handle the math to create a dark, gloomy aesthetic. "
                "OFFSET MUST be strictly negative across all channels (e.g., R: -0.02, G: -0.03, B: -0.02) to sink the shadows. WARNING: In negative Offsets, the number closest to 0 dominates. If G is -0.01 and B is -0.04, the shadows will turn GREEN. You MUST keep Green lower or equal to the others in negative Offsets. "
                "POWER MUST go ABOVE 1.00 (e.g., 1.10 to 1.30) to aggressively DARKEN the midtones. Reduce CDL Saturation (0.85 to 0.95)."
            ),
            "Natural Fix": (
                "\n\n7. 🌿 STYLE OVERRIDE: NATURAL FIX (CRITICAL): Do not apply stylistic color casts. Your goal is strictly corrective, returning the image to a clean, balanced state. "
                "- KEEP CDL Offset strictly at 0.00. "
                "- NO DOUBLE COLORING: If you use Temperature to fix a white balance issue, you MUST keep CDL Slope and Power completely color-neutral (R=1.00, G=1.00, B=1.00). Do not mix Temperature shifts with CDL color shifts. "
                "- EXPOSURE & CONTRAST AWARENESS: Analyze the lighting first. If the image is flat/overcast, boost Contrast (e.g., 1.05-1.10) and Color Slice 'Sat'. However, for Night shots or Harsh Sunny days with deep shadows, keep Contrast near 1.00 to avoid crushing the blacks, and rely mainly on subtle Saturation to bring out the natural colors."
            )
        }

        # 4. Η ΔΥΝΑΜΙΚΗ ΕΝΩΣΗ (Εδώ πιάνει το req.style από το frontend)
        selected_override = style_overrides.get(req.style, style_overrides["Natural Fix"])
        final_system_instr = base_prompt + selected_override + json_format

        user_prompt_text = f"Analyze this image and generate the precise ASC CDL and slider values for a {req.style} look."
    # =========================================================
    # --- 2. LOG MODE (THE STRICT "POINT 0" PRE-LUT SYSTEM) ---
    # =========================================================
    else:
        base_prompt = (
            "You are a Senior DIT and Digital Colorist analyzing a flat LOG screenshot. "
            "CRITICAL: DO NOT try to make this image look colorful or cinematic (Rec.709). IT IS SUPPOSED TO LOOK GRAY. "
            "Your ONLY job is to calculate the 'Pre-LUT Primary Balance' (Point 0). "
            "\n\nSTRICT MATHEMATICAL RULES (DO NOT BREAK THESE): "
            "0. PRECISION: You MUST output all values with EXACTLY 3 DECIMAL PLACES (e.g., 0.850, -0.024). "
            "1. SLOPE (Exposure): You must calculate exposure by acting as a Digital Waveform Monitor using the '3-Step Visual Anchor' method: "
            "- STEP 1 (Identify): Find midtone 'Visual Anchors' in the image (e.g., human skin, asphalt, neutral walls, grass). "
            "- STEP 2 (Evaluate): How bright do these anchors look right now in this flat JPEG? (e.g., muddy/dark, perfectly middle, bright/washed out). "
            "- STEP 3 (Target): Read the specific Camera Profile below. It will tell you exactly how these anchors SHOULD look for that specific LOG. "
            "Calculate the Slope needed to push the anchors to the Target. DO NOT BE TIMID. If they are too bright, drop the Slope aggressively (e.g., 0.750 - 0.950). If too dark, raise it (e.g., 1.050 - 1.250). "
            "HARD RULE: The R, G, and B values in Slope MUST BE EXACTLY IDENTICAL. "
            "2. OFFSET (Black Floor & Tint): Pull down the milky blacks. Range: -0.080 to +0.050. HARD RULE: To remove micro-tints, the difference between R, G, and B MUST NEVER exceed 0.005. "
            "3. POWER (Gamma): Keep exactly at 1.000 for R, G, and B. "
            "4. SATURATION: STRICTLY between 1.000 and 1.050. Do NOT add color. "
            "5. COLOR SLICE: Density (Den) must be exactly 0.000."
        )

        camera_overrides = {
            "Apple Log": "\n\n🎥 CAMERA PROFILE: Apple Log. TARGET VISUAL: Midtones (like skin or concrete) should look quite bright and clearly visible, sitting right in the visual middle of the image. If the anchors look muddy, dim, or dark, RAISE the Slope boldly. If they look overexposed, lower it. Use ULTRA-MICRO-ADJUSTMENT (max 0.005 diff) in Offset to neutralize magenta/green.",
            "Sony S-Log3": "\n\n🎥 CAMERA PROFILE: Sony S-Log3. TARGET VISUAL: Midtones MUST look slightly dim and 'muddy' (sitting just below the visual middle). Skin should NOT look perfectly bright. If the image looks bright or naturally exposed, it is TOO HIGH—drop the Slope to make it slightly dim. Use ULTRA-MICRO-ADJUSTMENT (max 0.005 diff, e.g., lowering Green) in Offset to neutralize its notorious green/yellow tint.",
            "Canon C-Log": "\n\n🎥 CAMERA PROFILE: Canon C-Log 2/3. TARGET VISUAL: Midtones must look noticeably dim. The sky MUST be a dull gray, NOT bright white. If you see bright/washed-out skies or overly bright faces, drop the Slope aggressively to crush them down to a dull state. Use ULTRA-MICRO-ADJUSTMENT (max 0.005 diff) in Offset to fix warm/red casts.",
            "Panasonic V-Log": "\n\n🎥 CAMERA PROFILE: Panasonic V-Log. TARGET VISUAL: Midtones should look slightly dim. However, V-Log inherently records them extremely dark/crushed. If the anchors are barely visible or completely in the shadows, RAISE the Slope to bring them up to a slightly dim, visible state. Keep RGB Offset differences under 0.003.",
            "Arri LogC3": "\n\n🎥 CAMERA PROFILE: Arri LogC3. TARGET VISUAL: Midtones should be slightly dim and perfectly neutral. Adjust Slope strictly to make anchors sit just below the visual middle. Identical RGB values in Slope, identical in Offset."
        }

        selected_camera = camera_overrides.get(req.camera_profile, camera_overrides["Apple Log"])
        final_system_instr = base_prompt + selected_camera + json_format
        
        user_prompt_text = f"Analyze this {req.camera_profile} Log image. Calculate the precise, micro-adjustment ASC CDL values needed to achieve a perfectly neutral Point 0. Do NOT normalize the image."
    
    
    try:
        image_data = req.image_base64.split(",")[-1]
        image_bytes = base64.b64decode(image_data)
        
        response = client_google.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                types.Part.from_text(text=user_prompt_text)
            ],
            config=types.GenerateContentConfig(
                system_instruction=final_system_instr, 
                temperature=0.2, 
                response_mime_type="application/json" 
            )
        )
        
        # --- ΚΑΘΑΡΙΣΜΟΣ ΑΠΑΝΤΗΣΗΣ ΑΠΟ ΤΟ AI ---
        ai_text = response.text.strip()
        if ai_text.startswith("```json"):
            ai_text = ai_text[7:]
        if ai_text.endswith("```"):
            ai_text = ai_text[:-3]
        ai_text = ai_text.strip()

        # Μετατροπή του καθαρού κειμένου σε JSON
        final_json = json.loads(ai_text)
        
        # Αφαίρεση 2 credits
        current_user.credits -= 2
        db.commit() 
            
        # ΚΡΑΤΑΣ ΜΟΝΟ ΑΥΤΟ ΤΟ RETURN
        return {"result": final_json, "credits_left": current_user.credits}
        
    except Exception as e:
        log_msg(f"❌ Color Grade Error: {e}")
        raise HTTPException(500, "Failed to analyze image colors.")


# Regex για έλεγχο μορφής email
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

class UserRegister(BaseModel):
    email: str
    password: str

@app.post("/register")
def register_user(user: UserRegister, db: Session = Depends(get_db)):
    if not EMAIL_REGEX.match(user.email):
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    
    if len(user.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")

    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    hashed_pw = get_password_hash(user.password)
    
    # Δημιουργία τυχαίου token για το email
    verification_token = secrets.token_urlsafe(32)
    
    # ⚠️ Προσοχή: credits=0 και is_verified=False
    new_user = User(
        email=user.email, 
        hashed_password=hashed_pw, 
        credits=0, 
        is_verified=False,
        verification_token=verification_token
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # ΣΤΕΛΝΟΥΜΕ ΤΟ EMAIL ME TO RESEND
    verify_link = f"{FRONTEND_URL}/?verify={verification_token}" # Πρέπει να φτιάξεις μια σελίδα /verify στο frontend σου
    
    try:
        # Το HTML email template
        html_content = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 0; padding: 40px 20px; color: #333333;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">
                
                <div style="background-color: #111827; padding: 30px; text-align: center;">
                    <h1 style="color: #ffffff; margin: 0; font-size: 26px; letter-spacing: 1px; font-weight: 800;">
                        Vincicut <span style="color: #6366f1;">AI</span>
                    </h1>
                </div>
                
                <div style="padding: 40px 30px;">
                    <h2 style="margin-top: 0; color: #111827; font-size: 22px;">Welcome aboard! 🚀</h2>
                    <p style="font-size: 16px; line-height: 1.6; color: #4b5563; margin-bottom: 25px;">
                        You're just one step away from unlocking the power of Vincicut AI. Please verify your email address to activate your account and claim your <strong>4 Free Credits</strong> instantly.
                    </p>
                    
                    <div style="text-align: center; margin: 35px 0;">
                        <a href="{verify_link}" style="background-color: #6366f1; color: #ffffff; padding: 14px 32px; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px; display: inline-block;">
                            Verify Email & Claim Credits
                        </a>
                    </div>
                    
                    <p style="font-size: 14px; color: #6b7280; margin-bottom: 0; margin-top: 30px; border-top: 1px solid #e5e7eb; padding-top: 20px;">
                        If the button doesn't work, copy and paste this link into your browser:<br>
                        <a href="{verify_link}" style="color: #6366f1; word-break: break-all; text-decoration: underline;">{verify_link}</a>
                    </p>
                </div>
                
                <div style="background-color: #f9fafb; padding: 20px 30px; text-align: center;">
                    <p style="margin: 0; font-size: 13px; color: #9ca3af;">
                        © 2026 Vincicut AI. All rights reserved.<br>
                        If you didn't create an account, you can safely ignore this email.
                    </p>
                </div>
                
            </div>
        </div>
        """

        resend.Emails.send({
            "from": "Vincicut AI <support@vincicutai.com>",
            "to": user.email,
            "subject": "Verify your email to get 4 Free Credits! 🎁",
            "html": html_content
        })
    except Exception as e: 
        print(f"Error sending email: {e}")
        # Δεν κρασάρουμε το app αν πέσει το email, απλά το καταγράφουμε

    return {"message": "Verification sent to email. Please check your inbox!"}


# --- ΝΕΟ ENDPOINT ΓΙΑ ΤΟ CLICK ΤΟΥ EMAIL ---
@app.post("/verify-email")
def verify_user_email(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.verification_token == token).first()
    
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link.")
    
    # Τώρα του δίνουμε τα credits!
    user.is_verified = True
    user.verification_token = None
    user.credits = 4 
    db.commit()
    
    return {"message": "Email verified successfully! You got 4 free credits. You can now log in."}

# --- STRIPE PAYMENTS ---

class CheckoutRequest(BaseModel):
    plan: str # Θα είναι "creator" ή "pro"

@app.post("/create-checkout-session")
async def create_checkout_session(req: CheckoutRequest, current_user: User = Depends(get_current_user)):
    price_id = ""
    coupon_id = None # Αρχικά ΔΕΝ έχει κουπόνι
    
    if req.plan == "creator":
        price_id = "price_1T3dH9FEGIb2vXU0uxqx9cYg" 
        # 👇 Αν ΔΕΝ έχει ξαναγοράσει (είναι νέος), του δίνουμε το κουπόνι!
        if not current_user.stripe_customer_id:
            coupon_id = "FIRSTMONTH_CREATOR"            
    elif req.plan == "pro":
        price_id = "price_1T3dHWFEGIb2vXU08IEVULAI"
        if not current_user.stripe_customer_id:
            coupon_id = "FIRSTMONTH_PRO"                
    else:
        raise HTTPException(status_code=400, detail="Invalid plan selected")

    try:
        domain_url = "https://video-ai-app-production.up.railway.app" 
        
        # Φτιάχνουμε τις παραμέτρους δυναμικά για να του δώσουμε το παλιό του ID αν υπάρχει
        session_kwargs = {
            "payment_method_types": ['card'],
            "line_items": [{'price': price_id, 'quantity': 1}],
            "mode": 'subscription',
            "client_reference_id": str(current_user.id),
            "success_url": f"{domain_url}/static/index.html?payment=success",
            "cancel_url": f"{domain_url}/static/index.html?payment=cancelled",
            "metadata": {"plan": req.plan},
            "custom_text": {"submit": {"message": "You can cancel your subscription at any time."}}
        }
        
        # Αν είναι ΠΑΛΙΟΣ πελάτης, δίνουμε στο Stripe το παλιό του ID για να μην φτιάξει διπλό!
        if current_user.stripe_customer_id:
            session_kwargs["customer"] = current_user.stripe_customer_id
        else:
            session_kwargs["customer_email"] = current_user.email
            
        # Προσθέτουμε την έκπτωση ΜΟΝΟ αν υπάρχει coupon_id
        if coupon_id:
            session_kwargs["discounts"] = [{'coupon': coupon_id}]

        session = stripe.checkout.Session.create(**session_kwargs)
        return {"checkout_url": session.url}
    
    except Exception as e:
        log_msg(f"Stripe Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload or signature")

    # 1. ΠΡΩΤΗ ΑΓΟΡΑ / ΕΠΑΝΑΓΟΡΑ (checkout.session.completed)
    if event.type == 'checkout.session.completed':
        session = event.data.object
        
        # Σωστή κλήση αντικειμένου για το νέο Stripe SDK
        user_id = session.client_reference_id
        if user_id:
            user = db.query(User).filter(User.id == int(user_id)).first()
            if user:
                purchased_plan = getattr(session.metadata, 'plan', None) if session.metadata else None
                
                if purchased_plan == "creator":
                    user.credits += 50
                    user.subscription_plan = "creator"
                elif purchased_plan == "pro":
                    user.credits += 120
                    user.subscription_plan = "pro"
                
                user.is_premium = True
                user.stripe_customer_id = session.customer 
                
                db.commit()
                log_msg(f"💰 LIVE PAYMENT SUCCESS! User {user.email} bought {purchased_plan}!")

    # 2. ΑΥΤΟΜΑΤΗ ΑΝΑΝΕΩΣΗ ΕΠΟΜΕΝΟΥ ΜΗΝΑ (invoice.paid)
    elif event.type == 'invoice.paid':
        invoice = event.data.object
        if invoice.billing_reason == 'subscription_cycle':
            user = db.query(User).filter(User.stripe_customer_id == invoice.customer).first()
            if user:
                if user.subscription_plan == "creator":
                    user.credits += 50
                elif user.subscription_plan == "pro":
                    user.credits += 120
                db.commit()
                log_msg(f"🔄 MONTHLY RENEWAL: Credits given to {user.email}")

    # 3. ΑΚΥΡΩΣΗ ΣΥΝΔΡΟΜΗΣ (customer.subscription.deleted)
    # 2. ΟΡΙΣΤΙΚΗ ΔΙΑΓΡΑΦΗ ΣΥΝΔΡΟΜΗΣ (Webhook Event)
    elif event.type == 'customer.subscription.deleted':
        subscription = event.data.object
        
        # Λογική "Bulletproof": Παίρνουμε το ID του πελάτη ό,τι κι αν στείλει το Stripe
        cust_id = getattr(subscription, 'customer', None)
        
        # Αν το customer είναι αντικείμενο, πάρε το .id του. Αν είναι ήδη string, κράτα το.
        if hasattr(cust_id, 'id'):
            cust_id = cust_id.id
        
        if cust_id:
            # Ψάχνουμε τον χρήστη στη βάση με το Stripe Customer ID
            user = db.query(User).filter(User.stripe_customer_id == cust_id).first()
            if user:
                user.is_premium = False
                user.subscription_plan = "free"
                db.commit()
                log_msg(f"💔 SUBSCRIPTION CANCELED: User {user.email} is now free.")
            else:
                log_msg(f"⚠️ Webhook received for unknown customer ID: {cust_id}")
        else:
            log_msg("❌ CRITICAL: Could not extract customer ID from Stripe event.")

    return {"status": "success"}

@app.post("/token")
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # 1. Βρίσκουμε τον χρήστη
    user = db.query(User).filter(User.email == form_data.username).first()
    
    # 2. Ελέγχουμε τον κωδικό
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email first. Check your inbox.")
    
    
    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer", "credits": user.credits}


class ResetPasswordData(BaseModel):
    token: str
    new_password: str

@app.post("/forgot-password")
def forgot_password(email: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        # 🛡️ Ασφάλεια: Πάντα λέμε το ίδιο μήνυμα, ακόμα κι αν δεν υπάρχει το email (για να μην καταλαβαίνουν ποιοι χρήστες υπάρχουν)
        return {"message": "If that email exists, a reset link has been sent."}
        
    reset_token = secrets.token_urlsafe(32)
    user.reset_password_token = reset_token
    user.reset_password_expires = datetime.utcnow() + timedelta(hours=1) # Λήγει σε 1 ώρα
    db.commit()
    reset_link = f"{FRONTEND_URL}/?reset={reset_token}" # Θέλει σελίδα στο frontend
    
    try:
        resend.Emails.send({
            "from": "Vincicut AI <support@vincicutai.com>",
            "to": user.email,
            "subject": "Password Reset Request",
            "html": f"<p>Click the link below to reset your password. This link expires in 1 hour.</p><br><a href='{reset_link}'>Reset Password</a>"
        })
    except Exception as e:
        print(f"Error sending email: {e}")
        
    return {"message": "If that email exists, a reset link has been sent."}

@app.post("/reset-password")
def reset_password(data: ResetPasswordData, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_password_token == data.token).first()
    
    # Ελέγχουμε αν υπάρχει ο χρήστης και αν το token δεν έχει λήξει
    if not user or not user.reset_password_expires or user.reset_password_expires < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
        
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
        
    user.hashed_password = get_password_hash(data.new_password)
    user.reset_password_token = None
    user.reset_password_expires = None
    db.commit()
    
    return {"message": "Password has been reset successfully. You can now log in."}

@app.get("/users/me")
async def read_users_me(current_user: User = Depends(get_current_user)):
    plan = getattr(current_user, 'subscription_plan', 'free')
    # 👇 ΝΕΟ: Ελέγχουμε αν έχει ξανακάνει συνδρομή ποτέ (αν έχει stripe_customer_id)
    had_sub = True if current_user.stripe_customer_id else False
    return {
        "email": current_user.email, 
        "credits": current_user.credits, 
        "is_premium": current_user.is_premium, 
        "plan": plan,
        "had_subscription": had_sub # Το στέλνουμε στο app.js
    }


@app.get("/my-projects")
def get_my_projects(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    projects = db.query(Project).filter(Project.user_id == current_user.id).order_by(Project.upload_date.desc()).all()
    return [
        {
            "id": proj.id,
            "filename": proj.filename,
            "status": proj.status,
            "date": proj.upload_date,
            "mode": proj.mode,
            "ai_response": proj.history_json if proj.mode == "chat" else proj.ai_response_json
        }
        for proj in projects
    ]

# --- ΔΙΑΓΡΑΦΗ PROJECT / CHAT ---
@app.delete("/projects/{project_id}")
def delete_project(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Διαγραφή και του αρχείου από το δίσκο (αν υπάρχει) για εξοικονόμηση χώρου
    # Υποθέτουμε ότι το filename είναι το αρχικό όνομα. Αν έχεις σώσει το path, βάζεις εκείνο.
    # Εδώ το αφήνουμε απλό, διαγράφει τουλάχιστον τη βάση δεδομένων.
    
    db.delete(project)
    db.commit()
    return {"message": "Project deleted successfully"}

# --- ΜΕΤΟΝΟΜΑΣΙΑ ΚΑΙ PIN PROJECT / CHAT ---
# Προσοχή: Εδώ έγινε `async def` και `await request.json()` για να μη σκάσει!
@app.put("/projects/{project_id}")
async def update_project(project_id: int, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    body = await request.json()
    
    if "filename" in body:
        project.filename = body["filename"]
        
    db.commit()
    return {"message": "Project updated successfully"}

# --- ΔΗΜΙΟΥΡΓΙΑ ΕΙΣΙΤΗΡΙΟΥ ΓΙΑ CLOUDFLARE ---
class PresignedUrlRequest(BaseModel):
    filename: str
    file_type: str

@app.post("/generate-presigned-url")
async def generate_presigned_url(request: PresignedUrlRequest, current_user: User = Depends(get_current_user)):
    try:
        # Φτιάχνουμε ένα μοναδικό όνομα αρχείου με UUID
        unique_filename = f"{uuid.uuid4()}_{request.filename}"
        
        # Ζητάμε το URL από το Cloudflare
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': R2_BUCKET_NAME,
                'Key': unique_filename,
                'ContentType': request.file_type
            },
            ExpiresIn=3600 # Λήγει σε 1 ώρα
        )
        
        return {
            "upload_url": presigned_url,
            "file_key": unique_filename
        }
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/upload/video")
async def upload_video(
    file_key: str = Form(...), 
    prompt: Optional[str] = Form(None), 
    mode: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    uploaded_files = []
    temp_files = []
    metadata = {}
    
    # Καθαρισμός προηγούμενης συνεδρίας
    active_video_session["clips_data"] = [] 

    # --- 👇 ΝΕΟΣ ΚΩΔΙΚΑΣ: ΔΗΜΙΟΥΡΓΙΑ PROJECT ΣΤΗ ΒΑΣΗ 👇 ---
    # Το file_key είναι το όνομα του αρχείου που δίνει το Cloudflare
    safe_filename = "".join(x for x in file_key if x.isalnum() or x in "._- ")
    
    new_project = Project(
        user_id=current_user.id,
        filename=safe_filename,
        status="processing",
        upload_date=datetime.utcnow()
    )
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    log_msg(f"📂 Project Created: ID {new_project.id} for User {current_user.email}")
    # ----------------------------------------------------------

    t_start = time.time()
    
    log_msg(f"📥 NEW UPLOAD (Cloudflare R2) | Mode: {mode} | Custom Prompt: {bool(prompt)}")
    
    try:
        ffmpeg_check = get_ffmpeg_command()
    except Exception as e:
        raise HTTPException(500, "FFmpeg binary missing.")

    try:
        # --- 1. SETUP & DOWNLOAD FROM CLOUDFLARE ---
        raw_name = f"raw_{int(time.time())}_{safe_filename}"
        comp_name = f"comp_{int(time.time())}_{safe_filename}.mp4"
        
        log_msg(f"📥 Downloading video from Cloudflare R2...")
        # Κατεβάζουμε το αρχείο από το Cloudflare κατευθείαν στον δίσκο του Railway (raw_name)
        s3_client.download_file(R2_BUCKET_NAME, file_key, raw_name)
        temp_files.append(raw_name)
        log_msg(f"✅ Download complete! Starting AI processing...")
        
        # Αποθηκεύουμε το path ΚΑΙ το mode (για να ξέρουμε μετά αν θέλουμε υποτίτλους)
        active_video_session["last_video_key"] = file_key
        active_video_session["current_mode"] = mode if mode else "custom"  # <--- ΣΗΜΑΝΤΙΚΟ
        
        metadata = get_video_metadata(raw_name)
        
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(executor, compress_video_sync, raw_name, comp_name)
        file_to_up = comp_name if success else raw_name
        if success: temp_files.append(comp_name)

        log_msg("🚀 Uploading to Gemini...")
        g_file = client_google.files.upload(file=file_to_up)
        while g_file.state.name == "PROCESSING":
            await asyncio.sleep(1)
            g_file = client_google.files.get(name=g_file.name)
        uploaded_files.append(g_file)
        
        # --- 2. ΕΠΙΛΟΓΗ PROMPT (ΤΑ ΔΙΚΑ ΣΟΥ) ---

        # Αυτό το χρειαζόμαστε για Custom και Viral (όχι για EDL που έχει δικό του JSON)
        required_json_format = (
            f"\n\n🚨 SYSTEM REQUIREMENT:"
            f"\nYou must output strictly valid JSON inside a code block."
            f"\nStructure: {{ \"viral_clips\": [ {{ \"start\": \"MM:SS\", \"end\": \"MM:SS\", \"title\": \"Title\", \"reason\": \"Why\", \"caption\": \"Text\", \"hashtags\": \"#tags\" }} ] }}"
        )

        final_prompt_text = ""

        if prompt and len(prompt.strip()) > 0:
            # --- CUSTOM MODE (ULTIMATE SMART) ---
            print("👉 Mode: CUSTOM. AI decides style & behavior.")
            
            style_instructions = (
                "\nRENDER STYLE RULES (Choose strictly based on user intent):"
                "\n- 'viral': Use if user asks for BOTH 'vertical' AND 'subtitles' (or says 'tiktok', 'shorts'). (Result: Vertical + Blur + Yellow Viral Subtitles)."
                "\n- 'subs': DEFAULT FOR SUBTITLES. Use if user asks for 'subtitles', 'captions' but does NOT explicitly ask for movie style. (Result: Original Aspect Ratio + Yellow Viral Subtitles)."
                "\n- 'movie_subs': Use ONLY if user EXPLICITLY asks for 'movie style', 'cinematic', or 'white' subtitles. (Result: Original Aspect Ratio + White Cinematic Subtitles)."
                "\n- 'vertical': Use if user asks for 'vertical', 'portrait', '9:16' BUT does NOT ask for subtitles. (Result: Vertical + Blur + NO Subs)."
                "\n- 'square': Use if user asks for 'square', 'instagram', 'post'. (Result: 1:1 Crop)."
                "\n- 'audio': Use if user asks for 'audio', 'sound', 'mp3'. (Result: MP3 Audio)."
                "\n- 'clean': DEFAULT. Use if user just asks to 'cut', 'trim', or extract a clip without effects. (Result: Original Video, No Subs)."
                "\n- 'gif': Use if user asks for 'gif', 'animation', 'loop'. (Result: Animated GIF)."
                "\n- 'screenshot': Use if user asks for 'screenshot', 'photo', 'image', 'frame', 'thumbnail'. (Result: JPG Image)."
                "\n- 'mute': Use if user asks to 'remove audio', 'mute', 'silent video'. (Result: Video without sound)."
            )

            behavior_instructions = (
                "\nBEHAVIOR & DURATION RULES (CRITICAL):"
                "\n1. DURATION DEFAULT: If the user request does NOT contain specific timestamps (e.g., '00:10') or words like 'highlight'/'part', YOU MUST process the ENTIRE VIDEO (start '00:00' to end)."
                "\n   - Example: 'Make it square' -> Return 1 clip, 00:00 to End."
                "\n   - Example: 'Add subtitles' -> Return 1 clip, 00:00 to End, style 'viral'."
                "\n2. NO UNWANTED TRIMMING: Do NOT cut the intro/outro or 'boring parts' unless the user specifically asks to 'trim', 'cut', or 'find best part'. Act as a file converter."
                "\n3. MULTIPLE CLIPS: You are ALLOWED to return multiple clips ONLY if the user asks to 'find all', 'extract segments', 'split', or 'list'. "
                "\n   - Example: 'Extract all meme sounds' -> Return multiple clips with style 'audio'."
            )

            required_json_format = (
                f"\n\n🚨 SYSTEM REQUIREMENT:"
                f"\nYou must output strictly valid JSON inside a code block."
                f"\nStructure: {{ \"viral_clips\": [ {{ \"start\": \"MM:SS\", \"end\": \"MM:SS\", \"title\": \"Title\", \"reason\": \"Why\", \"render_style\": \"style_name\" }} ] }}"
            )

            final_prompt_text = (
                f"User Request: {prompt}"
                f"\n\nINSTRUCTIONS: You are a Video Processing Tool. Your goal is to execute the user's command precisely."
                f"{behavior_instructions}"
                f"{style_instructions}"
                f"{required_json_format}"
            )
            
        elif mode == "rough_cut":
            # --- ROUGH CUT (EDL) - ΤΟ ΔΙΚΟ ΣΟΥ PROMPT ---
            print("👉 Mode: EDL / ROUGH CUT.")
            final_prompt_text = """You are a Senior Film Editor with 20 years of experience.
    OBJECTIVE: Analyze the footage and separate "Cinematic Action" from "Technical Garbage".

    CRITICAL MOTION RULES (READ CAREFULLY):
    1. WHIP PAN (KEEP): Rapid horizontal camera movement to change subjects. This is a transition. DO NOT CUT.
    2. HANDHELD (KEEP): Camera shake where the subject remains framed (e.g., Bourne Identity style). This is "Energy". DO NOT CUT.
    3. GARBAGE (CUT): 
        - Accidental Floor/Ceiling shots.
        - Focus Hunting (pulsing blur where nothing is clear).
        - Rolling Shutter Jello (extreme geometric warping).
    
    SAFETY PROTOCOL:
    If you are unsure if motion is "Action" or "Shake", KEEP IT. It is better to include a bad shot than cut a good one.
 
    OUTPUT FORMAT (JSON ONLY):
    {
      "bad_segments": [
        {"start": "MM:SS", "end": "MM:SS", "reason": "floor shot"},
        {"start": "MM:SS", "end": "MM:SS", "reason": "focus hunting"}
      ]
    }
    Return ONLY VALID JSON string. No Markdown."""

        elif mode == "viral":
            # --- VIRAL HIGHLIGHTS - ΤΟ ΔΙΚΟ ΣΟΥ PROMPT ΜΕ ΤΗ ΔΙΑΡΚΕΙΑ ---
            video_dur = metadata.get('duration', 0)
            
            if video_dur > 70:
                print(f"👉 Mode: VIRAL (Long Video {video_dur}s). Using MONETIZATION Rules.")
                final_prompt_text = (
                    f"\n\n🚨 CRITICAL TIKTOK MONETIZATION RULES (STRICT):"
                    f"\n1. DURATION: Each clip MUST be between 61 SECONDS and 75 SECONDS long."
                    f"\n   - This is REQUIRED for TikTok monetization (>1 min)."
                    f"\n   - DO NOT create clips shorter than 60 seconds."
                    f"\n   - If the moment is short, include context BEFORE and reaction AFTER to reach duration."
                    f"\n2. DIALOGUE: Prioritize segments with spoken words for subtitles."
                    f"\n3. OUTPUT FORMAT: Return ONLY VALID JSON inside a code block."
                ) + required_json_format
            else:
                print(f"👉 Mode: VIRAL (Short Video {video_dur}s). Using Best Segment Rules.")
                final_prompt_text = (
                    "Analyze this video and extract the single BEST segment available."
                    "\nRULES:"
                    "\n1. DURATION: Utilize as much of the video as necessary to tell a story."
                    "\n2. DIALOGUE: Ensure speech is preserved if present."
                ) + required_json_format
            
        else:
            # Fallback
            final_prompt_text = "Analyze this video and return a JSON summary." + required_json_format

        # --- 3. EXECUTE AI ---
        log_msg("🧠 AI Thinking...")
        chat = client_google.chats.create(model="gemini-2.5-flash", history=[])
        response = await loop.run_in_executor(executor, chat.send_message, uploaded_files + [final_prompt_text])
        
        # Αποθήκευση για clips (μόνο αν είναι Viral/Custom που έχουν viral_clips)
        try:
            json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response.text)
            if json_match:
                data = json.loads(json_match.group(1))
                active_video_session["clips_data"] = data.get("viral_clips", [])
        except: pass

        active_video_session["chat_session"] = chat
        
        # --- 👇 ΝΕΟΣ ΚΩΔΙΚΑΣ: ΑΠΟΘΗΚΕΥΣΗ RESULT & ΕΠΙΣΤΡΟΦΗ CREDITS 👇 ---
        new_project.status = "completed"
        new_project.ai_response_json = response.text
        
        # Αφαιρούμε 1 credit από τον χρήστη
        if current_user.credits > 0:
            current_user.credits -= 1
            
        db.commit()

        return {
            "status": "success", 
            "answer": response.text, 
            "metadata": metadata,
            "project_id": new_project.id,      # Επιστρέφουμε το ID
            "credits_left": current_user.credits # Επιστρέφουμε τα credits
        }
        # -------------------------------------------------------------------#

    except Exception as e:
        logging.error(f"Upload Error: {e}")
        # Σωστό καθάρισμα (Indentation fixed)
        if os.path.exists(raw_name):
            try:
                os.remove(raw_name)
            except:
                pass
        raise HTTPException(500, str(e))
        
    finally:
        for f in temp_files:
            try:
                os.remove(f)
            except:
                pass

# (Αυτό μπαίνει ΚΑΤΩ από το upload_video)

@app.post("/chat/video")
async def chat_video(req: ChatRequest):
    if not active_video_session["chat_session"]: raise HTTPException(400, "No active video session.")
    try:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(executor, active_video_session["chat_session"].send_message, req.question)
        try:
            start_idx = res.text.find("{")
            end_idx = res.text.rfind("}") + 1
            if start_idx != -1 and end_idx != -1:
                data = json.loads(res.text[start_idx:end_idx])
                if "viral_clips" in data:
                    active_video_session["clips_data"] = data["viral_clips"]
        except Exception:
            pass
        return {"answer": res.text}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/render/clip")
async def render_clip_endpoint(request: ClipRequest):
    file_key = active_video_session.get("last_video_key")
    clips_data = active_video_session.get("clips_data", [])
    current_mode = active_video_session.get("current_mode", "custom")
    
    if not file_key:
        raise HTTPException(400, "No active video found. Please upload again.")

    # Φτιάχνουμε το "εισιτήριο" για να διαβάσει το FFmpeg το βίντεο απευθείας από το Cloudflare
    try:
        video_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': R2_BUCKET_NAME, 'Key': file_key},
            ExpiresIn=3600
        )
    except Exception as e:
        raise HTTPException(500, f"Cloudflare link error: {e}")

    # 1. Βρίσκουμε το στυλ
    style = "clean" # Default
    if current_mode == "viral": 
        style = "viral"
    elif current_mode == "rough_cut": 
        style = "clean"
    else:
        # Custom Mode: Διαβάζουμε τι είπε το AI για αυτό το κλιπ
        if 0 <= request.index - 1 < len(clips_data):
            # Παίρνουμε την απάντηση του AI, την κάνουμε μικρά γράμματα και κόβουμε τα κενά
            raw_style = clips_data[request.index - 1].get("render_style", "clean").lower().strip()
            
            # Πιάνουμε όλα τα πιθανά συνώνυμα που μπορεί να σκεφτεί το AI
            if raw_style in ["screenshot", "thumbnail", "image", "photo", "frame", "picture"]:
                style = "screenshot"
            elif raw_style in ["gif", "animation", "loop"]:
                style = "gif"
            elif raw_style in ["audio", "mp3", "sound", "music"]:
                style = "audio"
            else:
                style = raw_style

    # 2. Ορίζουμε το όνομα (mp4, mp3, jpg, gif)
    ext = "mp4" # default
    if style == "audio": ext = "mp3"
    elif style == "screenshot": ext = "jpg"
    elif style == "gif": ext = "gif"
    filename = f"clip_{int(time.time())}_{request.index}.{ext}"
    output_path = os.path.join(OUTPUT_DIR, filename)
    
    start_sec = parse_time_str(request.start_time)
    end_sec = parse_time_str(request.end_time)

    # 3. Εκτέλεση
    loop = asyncio.get_running_loop()
    final_path = await loop.run_in_executor(
        executor, 
        create_pro_short_sync, 
        video_url,
        start_sec, 
        end_sec, 
        output_path,
        style 
    )

    if not final_path: raise HTTPException(500, "Render failed.")
    
    # Δηλώνουμε τον σωστό τύπο αρχείου για να μην μπερδεύεται η Javascript
    content_type = "video/mp4"
    if ext == "jpg": content_type = "image/jpeg"
    elif ext == "gif": content_type = "image/gif"
    elif ext == "mp3": content_type = "audio/mpeg"

    return FileResponse(
        path=final_path, 
        filename=os.path.basename(final_path), 
        media_type=content_type
    )

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Κάνουμε redirect στο link που ξέρουμε ότι δουλεύει 100%
    return RedirectResponse(url="/static/Favicorn.png")

@app.get("/")
async def root():
    return FileResponse("index.html") # ✅ Σωστό! Σβήσαμε το "static/"

@app.get("/upgrade-database")
def upgrade_database(db: Session = Depends(get_db)):
    try:
        # Τρέχει την εντολή κατευθείαν στη βάση σου
        db.execute(text("ALTER TABLE projects ADD COLUMN is_pinned BOOLEAN DEFAULT FALSE;"))
        db.commit()
        return {"message": "✅ ΕΠΙΤΥΧΙΑ! Η στήλη is_pinned προστέθηκε με ασφάλεια!"}
    except Exception as e:
        # Αν η εντολή έχει ήδη τρέξει παλιότερα, θα πετάξει error που θα το πιάσουμε εδώ
        return {"message": "Η στήλη υπάρχει ήδη ή υπήρξε σφάλμα", "error": str(e)}

@app.get("/upgrade-users-db")
def upgrade_users_db(db: Session = Depends(get_db)):
    queries = [
        "ALTER TABLE users ADD COLUMN verification_token VARCHAR;",
        "ALTER TABLE users ADD COLUMN reset_password_token VARCHAR;",
        "ALTER TABLE users ADD COLUMN reset_password_expires TIMESTAMP;",
        "UPDATE users SET is_verified = TRUE;"
    ]
    
    for q in queries:
        try:
            db.execute(text(q))
            db.commit()
        except Exception:
            db.rollback() # Αν πετάξει error (π.χ. υπάρχει ήδη), το αγνοεί και πάει στην επόμενη!
            
    return {"message": "✅ Η βάση ενημερώθηκε πλήρως και τα errors διορθώθηκαν! Δοκίμασε να κάνεις Login τώρα."}
if __name__ == "__main__":
    import uvicorn
    import os
    
    # 1. Διαβάζουμε το PORT
    port = int(os.environ.get("PORT", 8000))
    
    # 2. Σύνδεση στη βάση (Μέσα στο startup για ασφάλεια)
    log_msg("🚀 Connecting to database...")
    try:
        database.Base.metadata.create_all(bind=database.engine)
        log_msg("✅ Database connection successful!")
    except Exception as e:
        log_msg(f"❌ Database connection failed: {e}")

    # 3. Εκκίνηση του Server
    log_msg(f"🚀 SERVER STARTING on Port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
