import shutil,subprocess

shutil.copytree("config", "build/main.dist/config")
shutil.copytree("page", "build/main.dist/page")
subprocess.run(["git", "clone", "https://github.com/MaaXYZ/MaaAgentBinary", "build/main.dist/MaaAgentBinary"])