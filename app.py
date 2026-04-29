import os
import uuid
import zipfile
import shutil
import subprocess
import json
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

APP_NAME = "MPC Stem Backend"
BASE_DIR = Path(__file__).resolve().parent
JOBS_DIR = BASE_DIR / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def job_dir(job_id):
    return JOBS_DIR / job_id

def status_path(job_id):
    return job_dir(job_id) / "status.json"

def write_status(job_id, status, message="", download_ready=False):
    d = job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    with open(status_path(job_id), "w") as f:
        json.dump({
            "job_id": job_id,
            "status": status,
            "message": message,
            "download_ready": download_ready
        }, f)

def read_status(job_id):
    p = status_path(job_id)
    if not p.exists():
        return None
    with open(p, "r") as f:
        return json.load(f)

def separate_job(job_id, input_path, original_name):
    try:
        write_status(job_id, "processing", "Separating stems with Demucs...")

        d = job_dir(job_id)
        output_dir = d / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        command = [
            "python",
            "-m",
            "demucs",
            "-n",
            "htdemucs",
            "--out",
            str(output_dir),
            str(input_path)
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=1200
        )

        if result.returncode != 0:
            write_status(job_id, "error", result.stderr[-1000:])
            return

        separated_root = output_dir / "htdemucs"
        song_folders = list(separated_root.glob("*"))

        if not song_folders:
            write_status(job_id, "error", "No separated stems found.")
            return

        stems_folder = song_folders[0]
        expected_stems = ["vocals.wav", "drums.wav", "bass.wav", "other.wav"]
        zip_path = d / "stems.zip"

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for stem in expected_stems:
                stem_path = stems_folder / stem
                if stem_path.exists():
                    zipf.write(stem_path, arcname=stem)

            readme = f"""MPC Stem Backend Export

Original file:
{original_name}

Included stems:
- vocals.wav
- drums.wav
- bass.wav
- other.wav
"""
            zipf.writestr("README.txt", readme)

        write_status(job_id, "done", "Stems ready.", True)

    except subprocess.TimeoutExpired:
        write_status(job_id, "error", "Stem separation timed out. Try a shorter file.")

    except Exception as e:
        write_status(job_id, "error", str(e))


@app.get("/")
def home():
    return {
        "status": "running",
        "app": APP_NAME,
        "message": "Upload audio to /separate to create stems."
    }


@app.post("/separate")
async def separate_audio(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    d = job_dir(job_id)
    input_dir = d / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    original_name = file.filename or "upload.wav"
    safe_name = original_name.replace(" ", "_")
    input_path = input_dir / safe_name

    with open(input_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    write_status(job_id, "queued", "Upload received. Job queued.")
    background_tasks.add_task(separate_job, job_id, input_path, original_name)

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Stem separation started."
    }


@app.get("/status/{job_id}")
def get_status(job_id: str):
    status = read_status(job_id)
    if not status:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    return status


@app.get("/download/{job_id}")
def download_stems(job_id: str):
    zip_path = job_dir(job_id) / "stems.zip"

    if not zip_path.exists():
        return JSONResponse(status_code=404, content={"error": "Stems not ready"})

    return FileResponse(
        path=zip_path,
        filename="mpc-separated-stems.zip",
        media_type="application/zip"
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
