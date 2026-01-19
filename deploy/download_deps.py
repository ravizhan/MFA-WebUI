# /// script
# dependencies = [
#   "requirements-parser"
# ]
# ///

import subprocess
import sys
import requirements

def run_command(cmd):
    print(f"执行命令: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {e}")
        print(f"失败的命令: {' '.join(cmd)}")
        raise

def main():
    import os
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    
    os.environ.setdefault('PYTHONUNBUFFERED', '1')
    
    packages = []
    try:
        with open('requirements.txt', 'r') as f:
            for req in requirements.parse(f):
                if req.name:
                    packages.append(req.name)
    except FileNotFoundError:
        print("错误: 找不到 requirements.txt 文件")
        sys.exit(1)
    
    for pkg_name in packages:
        if pkg_name in ['nuitka', 'requirements-parser', 'packaging', 'pip', 'pylint', 'numpy', 'maafw', 'maaagentbinary', 'pillow']:
            continue
        try:
            run_command(["uv", "pip", "install", pkg_name, "--target", "build/deps"])
        except Exception as e:
            print(f"安装依赖失败: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()