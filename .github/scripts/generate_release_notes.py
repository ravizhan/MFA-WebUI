import httpx
import os
import sys
import uuid
import datetime

def get_latest_version(repo, current_version):
    """获取上一个版本的 tag name"""
    try:
        # 尝试获取最新 release
        resp = httpx.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=10)
        if resp.status_code == 200:
            latest_version = resp.json().get("tag_name")
            return latest_version
    except Exception as e:
        print(f"获取版本信息时出错: {e}", file=sys.stderr)
    return None

def main():
    repo = "ravizhan/MWU"
    current_version = os.getenv("GITHUB_REF_NAME")
    api_key = os.getenv("API_KEY")

    latest_version = get_latest_version(repo, current_version)

    patch_url = f"https://github.com/{repo}/compare/{latest_version}...{current_version}.patch"
    try:
        resp = httpx.get(patch_url, timeout=30)
        resp.raise_for_status()
        patch = resp.text
    except Exception as e:
        print(f"获取补丁内容失败: {e}", file=sys.stderr)
        return

    if not patch.strip():
        print("未发现代码变更内容。", file=sys.stderr)
        return

    prompt = """你是一个专业的软件更新日志分析助手。请阅读两个版本之间的代码变更补丁（git patch），并生成一份精炼的中文更新日志。

要求：
1. **严格分类**：只能从以下指定的 Section 中选择（若无相关变更则不显示该分类），且必须添加对应的 Emoji：
   - ✨ 新功能
   - 🐛 Bug修复
   - 📝 文档
   - 📦 依赖更新
   - ⚡ 性能优化
   - ♻️ 代码重构
   - 💄 样式
   - 👷 持续集成
   - 🔒 安全
2. **分类原则**：基于代码变更的实际影响进行归类，忽略 commit message 中可能不规范或错误的分类标识。
3. **内容精炼**：
   - 使用中文生成，每条记录必须精简为一句话概括。
   - 重点描述对用户或开发者有意义的变化，忽略单纯的版本号变更或自动生成文件的变动。
   - 尽量合并相似的变更项。
4. **输出格式**：各 Section 使用 ### 作为标题，下方使用无序列表（-）。

示例输出：
### ✨ 新功能
- 新增自动识别游戏窗口位置的功能
- 添加了对自定义配置文件的支持

### 🐛 Bug修复
- 修复了高分辨率屏幕下的点击偏移问题

### 📝 文档
- 更新了快速开始指南
"""

    data = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"以下是对比补丁内容：\n\n{patch}"}
        ],
        "temperature": 0.2
    }

    try:
        resp = httpx.post(
            "https://api.siliconflow.cn/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=data,
            timeout=180
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"]
        print(f"Token 使用情况: {resp.json().get('usage', {})}", file=sys.stderr)

        release_notes = f"## 更新日志（{datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).date().strftime('%Y-%m-%d')}）\n\n{result}"

        output_file = os.getenv('GITHUB_OUTPUT')
        delimiter = f"EOF_{uuid.uuid4().hex}"
        with open(output_file, "a", encoding="utf-8") as f:
            f.write(f"notes<<{delimiter}\n")
            f.write(release_notes)
            f.write(f"\n{delimiter}\n")
        print("已将更新日志写入 GITHUB_OUTPUT")
    except Exception as e:
        print(f"调用 AI 服务出错: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()

