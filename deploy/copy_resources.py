import shutil
import os
import json
from pathlib import Path

os.makedirs("build", exist_ok=True)
shutil.copytree("agent", "build/agent")
shutil.copytree("assets/resource", "build/resource")
shutil.copy2("assets/interface.json", "build")
with open("build/interface.json", "r", encoding="utf-8") as f:
    interface = json.load(f)
interface["version"] = os.getenv("tag", "dev")
interface["agent"] = {
    "child_exec": "./python/python.exe",
    "child_args": ["-u", "./agent/main.py"],
    "timeout": -1,
}
with open("build/interface.json", "w", encoding="utf-8") as f:
    json.dump(interface, f, ensure_ascii=False, indent=4)

shutil.copytree(
    Path("assets") / "MaaCommonAssets" / "OCR" / "ppocr_v4" / "zh_cn",
    Path("build") / "resource" / "base" / "model" / "ocr",
    dirs_exist_ok=True,
)
