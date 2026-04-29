import os
import uuid
import zipfile
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, UploadFile, File
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


@app.get("/")
def home():
    return {
        "status": "running",
        "app": APP_NAME,
        "message": "Upload audio to /separate to create stems."
    }


@app.post("/separate")
async def separate_audio(file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    job_dir = JOBS_DIR / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"

    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    original_name = file.filename or "upload.wav"
    safe_name = original_name.replace(" ", "_")
    input_path = input_dir / safe_name

    try:
        with open(input_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

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
            timeout=900
        )

        if result.returncode != 0:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Demucs failed",
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
            )

        separated_root = output_dir / "htdemucs"
        song_folders = list(separated_root.glob("*"))

        if not song_folders:
            return JSONResponse(
                status_code=500,
                content={"error": "No separated stems found."}
            )

        stems_folder = song_folders[0]
        expected_stems = ["vocals.wav", "drums.wav", "bass.wav", "other.wav"]

        zip_path = job_dir / "stems.zip"

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

How to use:
1. Unzip this file.
2. Move stems to SD/USB.
3. Load stems into MPC.
4. Chop, loop, or assign to pads.
"""
            zipf.writestr("README.txt", readme)

        return FileResponse(
            path=zip_path,
            filename="mpc-separated-stems.zip",
            media_type="application/zip"
        )

    except subprocess.TimeoutExpired:
        return JSONResponse(
            status_code=504,
            content={"error": "Stem separation timed out. Try a shorter file."}
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Server error",
                "details": str(e)
            }
        )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
