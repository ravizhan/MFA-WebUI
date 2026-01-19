# /// script
# dependencies = [
#   "requirements-parser",
#   "nuitka",
#   "packaging",
# ]
# ///

import importlib.util
import importlib.metadata
import re
import subprocess
import sys
import requirements
from packaging.requirements import Requirement

BLACKLIST = {
    'pytest', 'pytest-cov', 'pytest-xdist', 'pytest-timeout', 'pytest-mock',
    'sphinx', 'sphinx-rtd-theme', 'furo', 'myst-parser', 'sphinx-copybutton',
    'mypy', 'pylint', 'flake8', 'ruff', 'black', 'tox', 'pre-commit',
    'twine', 'build', 'check-manifest', 'coverage', 'pyroma', 'setuptools',
    'wheel', 'sphinx-inline-tabs', 'sphinxext-opengraph', 'sphinx-autobuild',
    'pytest-mypy-plugins', 'pytest-pylint', 'pytest-black', 'nuitka',
    'requirements-parser', 'packaging', 'pip'
}

def run_command(cmd):
    print(f"执行命令: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"命令执行失败: {e}")
        print(f"失败的命令: {' '.join(cmd)}")
        raise

def get_import_name(dist_name):
    try:
        files = importlib.metadata.files(dist_name)
        if files:
            for f in files:
                if f.name == '__init__.py':
                    return f.parts[0]
    except:
        pass
    return dist_name.replace("-", "_")

def get_all_dependencies(package_names):
    all_deps = set()
    to_process = set(package_names)

    while to_process:
        pkg = to_process.pop()
        pkg_normalized = pkg.lower().replace("_", "-")
        
        if pkg_normalized in all_deps or pkg_normalized in ['python'] or pkg_normalized in BLACKLIST:
            continue
        
        all_deps.add(pkg_normalized)
        
        try:
            requires = importlib.metadata.requires(pkg_normalized)
            if requires:
                for req_str in requires:
                    try:
                        req = Requirement(req_str)
                        if req.marker and 'extra' in str(req.marker):
                            continue
                            
                        dep_name = req.name.lower().replace("_", "-")
                        if dep_name not in all_deps and dep_name not in BLACKLIST:
                            to_process.add(dep_name)
                    except Exception:
                        match = re.match(r'^([a-zA-Z0-9\-_]+)', req_str)
                        if match:
                            dep_name = match.group(1).lower().replace("_", "-")
                            if dep_name not in all_deps and dep_name not in BLACKLIST:
                                to_process.add(dep_name)
        except importlib.metadata.PackageNotFoundError:
            pass
            
    return all_deps

def main():
    import os
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    
    os.environ.setdefault('PYTHONUNBUFFERED', '1')
    
    print("=== 开始编译依赖包 ===")
    print(f"Python版本: {sys.version}")
    print(f"工作目录: {os.getcwd()}")
    
    initial_packages = []
    try:
        with open('requirements.txt', 'r') as f:
            for req in requirements.parse(f):
                if req.name:
                    initial_packages.append(req.name)
    except FileNotFoundError:
        print("错误: 找不到 requirements.txt 文件")
        sys.exit(1)

    print(f"初始包列表: {initial_packages}")

    try:
        run_command(["uv", "pip", "install"] + initial_packages)
    except Exception as e:
        print(f"安装初始依赖失败: {e}")
        sys.exit(1)

    full_manifest = get_all_dependencies(initial_packages)
    print(f"全量依赖清单 (共 {len(full_manifest)} 个): {full_manifest}")

    failed_packages = []
    
    for pkg_name in full_manifest:
        if pkg_name in ['nuitka', 'requirements-parser', 'packaging', 'pip', 'pylint', 'numpy', 'maafw', 'maaagentbinary', 'pillow']:
            continue
        if 'test' in pkg_name or 'doc' in pkg_name or 'sample' in pkg_name:
            continue

        print(f"\n>>> 正在处理: {pkg_name}")
        
        try:
            run_command(["uv", "pip", "install", pkg_name])
        except Exception as e:
            print(f"安装 {pkg_name} 失败: {e}")
            failed_packages.append(pkg_name)
            continue

        import_name = get_import_name(pkg_name)
        spec = importlib.util.find_spec(import_name)
        
        if not spec or not spec.submodule_search_locations:
            print(f"跳过 {pkg_name}: 找不到包路径（可能是单文件模块或标准库）")
            continue

        pkg_path = spec.submodule_search_locations[0]
        
        nuitka_cmd = [
            sys.executable, "-m", "nuitka",
            "--mode=package",
            "--output-dir=build/deps",
            "--nofollow-imports",
            "--remove-output",
            "--assume-yes-for-downloads",
            pkg_path
        ]
        
        try:
            run_command(nuitka_cmd)
            print(f"✓ {pkg_name} 编译成功")
        except Exception as e:
            print(f"✗ 编译 {pkg_name} 失败: {e}")
            failed_packages.append(pkg_name)
    
    print("\n=== 编译完成 ===")
    print(f"总处理包数: {len(full_manifest)}")
    print(f"失败包数: {len(failed_packages)}")
    
    if failed_packages:
        print(f"失败的包: {failed_packages}")
        print("中断构建")
        sys.exit(1)
    else:
        print("所有包编译成功！")

if __name__ == "__main__":
    main()