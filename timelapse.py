import os
import glob
import subprocess
from pathlib import Path
from db import get_session_measurements

def generate_timelapse(session_id, db_conn):
    """
    Generates an mp4 timelapse from all valid photos in the given session.
    """
    try:
        meds = get_session_measurements(db_conn, session_id)
        if not meds:
            return None
            
        # Extract valid photo absolute paths chronologically
        photo_paths = []
        for m in meds:
            # m is a sqlite3.Row from db.get_session_measurements
            foto = m["foto_path"]
            if foto and os.path.exists(foto):
                photo_paths.append(foto)
                
        if len(photo_paths) < 2:
            return None # Not enough photos for a video
            
        # Create a text file mapping all frame paths for ffmpeg concat
        concat_file = Path(f"data/concat_{session_id}.txt").resolve()
        with open(concat_file, "w") as f:
            for p in photo_paths:
                # ffmpeg requires paths to be properly escaped or single quoted
                f.write(f"file '{p}'\nduration 0.25\n")
        
        output_file = Path(f"data/timelapse_{session_id}.mp4").resolve()
        
        # FFmpeg command to read concat file and output a web-friendly H264 MP4
        # We add '-vf format=yuv420p' to ensure compatibility across browsers, Apple devices etc.
        cmd = [
            "ffmpeg", "-y", "-v", "warning",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(output_file)
        ]
        
        subprocess.run(cmd, check=True)
        
        # Clean up concat file
        try:
            os.remove(concat_file)
        except OSError:
            pass
            
        if output_file.exists():
            return str(output_file)
            
    except Exception as e:
        print(f"⚠️ Error creating timelapse: {e}")
        
    return None
