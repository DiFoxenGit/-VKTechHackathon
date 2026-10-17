"""Local launch using ignored server .env. Never prints environment values."""
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))


def load_server_env():
    path=ROOT/".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key,value=line.split("=",1)
                os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))


if __name__=="__main__":
    import uvicorn
    load_server_env()
    uvicorn.run("designer.app:create_app",factory=True,host="127.0.0.1",port=int(os.getenv("BACKEND_PORT","8000")))
