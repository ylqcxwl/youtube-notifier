# YouTube 视频更新通知程序说明文档

---

## 程序概述

本程序是一个 **无需 YouTube API 密钥** 的 YouTube 视频更新监控工具，使用 **RSS Feed** 检测频道更新，通过 **Telegram** 发送通知。

### 功能特点
- 无需 API Key（使用公开 RSS）
- 支持多个频道监控
- 频道ID 存储在 `channels.txt`（TXT 格式，易修改）
- 自动保存上次视频状态（`state.json`）
- 通过 Telegram 发送 **视频封面 + 标题 + 时间 + 简介 + 链接**
- 在 GitHub Actions 自动运行
- 支持手动触发或定时运行

---

## 目录结构

```plaintext
youtube-notifier/
├── main.py                     # 主程序
├── channels.txt                # 频道ID列表（TXT格式）
├── state.json                  # 状态记录（自动生成）
└── .github/
    └── workflows/
        └── update-check.yml    # GitHub Actions 配置文件
创建方法（首次部署）
1. 创建 GitHub 仓库
登录 GitHub
点击右上角 + → New repository
仓库名建议：youtube-notifier
选择 Public 或 Private（建议 Private）
勾选 Add a README file
点击 Create repository
2. 创建 Telegram Bot
打开 Telegram，搜索 @BotFather
发送 /newbot
按提示输入机器人名称和用户名
获取 Bot Token（格式：123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ）
获取 Chat ID：
给你的 Bot 发送任意消息
打开浏览器访问：
https://api.telegram.org/bot<你的TOKEN>/getUpdates
找到 "chat":{"id":123456789} → 123456789 就是你的 Chat ID
3. 添加文件到仓库
文件 1：main.py
import feedparser
import requests
import json
import os
import sys
from datetime import datetime
import time

# ==================== 配置 ====================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

STATE_FILE = 'state.json'
CHANNELS_FILE = 'channels.txt'  # TXT格式，每行一个ID

# ==================== 加载频道ID ====================
def load_channels():
    if not os.path.exists(CHANNELS_FILE):
        print(f"警告: {CHANNELS_FILE} 不存在，使用空列表。")
        return []
    
    channel_ids = []
    with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):  # 忽略空行和注释
                channel_ids.append(line)
    return channel_ids

# ==================== 状态管理 ====================
def load_state(channel_ids):
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
    else:
        state = {}
    for cid in channel_ids:
        if cid not in state:
            state[cid] = {'last_video_id': None, 'last_published': None}
    return state

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=4, ensure_ascii=False)

# ==================== 频道检测 ====================
def check_channel_id(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    feed = feedparser.parse(rss_url)
    if feed.bozo:
        print(f"频道ID {channel_id} 无效或无法访问。")
        return False
    print(f"频道ID {channel_id} 有效 → {feed.feed.get('title', '未知频道')}")
    return True

# ==================== 获取视频 ====================
def get_latest_videos(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    feed = feedparser.parse(rss_url)
    if feed.bozo:
        print(f"无法获取频道 {channel_id} 的RSS")
        return []

    videos = []
    for entry in feed.entries[:5]:
        video = {
            'title': entry.title,
            'link': entry.link,
            'video_id': entry.yt_videoid,
            'description': entry.get('media_description', '') or entry.get('summary', ''),
            'thumbnail': entry.media_thumbnail[0]['url'] if entry.get('media_thumbnail') else '',
            'published': entry.published
        }
        videos.append(video)
    return videos

# ==================== 时间解析 ====================
def parse_iso_time(iso_str):
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.timestamp()
    except:
        try:
            return time.mktime(time.strptime(iso_str, "%a, %d %b %Y %H:%M:%S %Z"))
        except Exception as e:
            print(f"时间解析失败: {iso_str} - {e}")
            return 0

# ==================== Telegram通知 ====================
def send_telegram_notification(video):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram 配置缺失，跳过通知")
        return

    message = (
        f"*新视频更新！*\n\n"
        f"**标题**：{video['title']}\n"
        f"**时间**：{video['published']}\n"
        f"**简介**：{video['description'][:300]}{'...' if len(video['description']) > 300 else ''}\n"
        f"[观看视频]({video['link']})"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'photo': video['thumbnail'],
        'caption': message,
        'parse_mode': 'Markdown'
    }
    try:
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code == 200:
            print(f"通知已发送: {video['title']}")
        else:
            print(f"Telegram 发送失败: {r.text}")
    except Exception as e:
        print(f"Telegram 请求异常: {e}")

# ==================== 主逻辑 ====================
def check_updates():
    channel_ids = load_channels()
    if not channel_ids:
        print("无频道ID配置，退出。")
        return

    state = load_state(channel_ids)
    updated = False

    for channel_id in channel_ids:
        videos = get_latest_videos(channel_id)
        if not videos:
            continue

        latest = videos[0]
        last_id = state.get(channel_id, {}).get('last_video_id')
        last_time = state.get(channel_id, {}).get('last_published')
        current_time = parse_iso_time(latest['published'])

        if latest['video_id'] != last_id:
            if last_time:
                last_timestamp = parse_iso_time(last_time)
                if current_time > last_timestamp:
                    send_telegram_notification(latest)
                    state[channel_id] = {
                        'last_video_id': latest['video_id'],
                        'last_published': latest['published']
                    }
                    updated = True
            else:
                send_telegram_notification(latest)
                state[channel_id] = {
                    'last_video_id': latest['video_id'],
                    'last_published': latest['published']
                }
                updated = True

    if updated:
        save_state(state)
    else:
        print("无新视频更新")

# ==================== 入口 ====================
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--check-id' and len(sys.argv) > 2:
        check_channel_id(sys.argv[2])
    else:
        check_updates()
文件 2：channels.txt
# YouTube 频道ID，每行一个，支持 # 注释
UC_x5XG1OV2P6uZZ5FSM9Ttw
# UC_another_channel_id_here
文件 3：state.json
{}
文件 4：.github/workflows/update-check.yml
name: Check YouTube Updates

on:
  schedule:
    - cron: '0 1 * * *'  # 香港时间每天早上 9:00 运行
  workflow_dispatch:

permissions:
  contents: write

jobs:
  check-updates:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install feedparser requests

      - name: Run script
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python main.py

      - name: Commit and push state file
        run: |
          git config --global user.name 'GitHub Actions'
          git config --global user.email 'actions@github.com'
          git add state.json channels.txt
          if git diff --staged --quiet; then
            echo "No changes to commit"
          else
            git commit -m "Update state: $(date -u +'%Y-%m-%d %H:%M UTC')"
            git push
          fi
4. 设置 Secrets（环境变量）
进入仓库 → Settings → Secrets and variables → Actions
点击 New repository secret，添加两个：
Name
Value
TELEGRAM_TOKEN
你的 Bot Token
TELEGRAM_CHAT_ID
你的 Chat ID（数字）
5. 提交所有文件
git add .
git commit -m "feat: initial YouTube notifier"
git push
修改方法
1. 修改运行时间（香港时间）
编辑 .github/workflows/update-check.yml 中的 cron：
on:
  schedule:
    - cron: '0 1 * * *'  # 香港时间 09:00
需求
cron 表达式
说明
每天 HKT 09:00
0 1 * * *
推荐
每 2 小时
0 */2 * * *

每 30 分钟
*/30 * * * *

工作日 HKT 09:00
0 1 * * 1-5
周一至周五
使用 crontab.guru 验证时间
2. 添加/删除频道
编辑 channels.txt：
UC_x5XG1OV2P6uZZ5FSM9Ttw
UC_9k7iRj...
# UC_disabled_channel  # 注释掉即禁用
修改后 提交 push 即可生效
3. 手动运行（立即检查）
进入 GitHub 仓库 → Actions
选择 Check YouTube Updates
点击右侧 Run workflow → Run workflow
4. 查看运行日志
Actions → 选择最近一次运行 → 点击 job → 查看输出
成功时会看到：
通知已发送: XXX
Update state: 2025-11-11 01:00 UTC
5. 检测频道ID是否正确（本地）
python main.py --check-id UC_x5XG1OV2P6uZZ5FSM9Ttw
输出：
频道ID UC_x5XG1OV2P6uZZ5FSM9Ttw 有效 → Google Developers
常见问题
问题
解决方案
没有收到通知
检查 Secrets 是否正确、Bot 是否被拉黑
git push 403
确认 permissions: contents: write 在 on 之后
时间不对
所有时间基于 UTC，香港时间 = UTC+8
频道ID无效
使用 --check-id 验证，或在 YouTube 频道页面查看 URL
安全提示
不要公开 TELEGRAM_TOKEN
建议仓库设为 Private
state.json 包含历史记录，可定期清理
维护者信息
作者：Grok + 你
更新时间：2025年11月11日
支持：如有问题，提交 Issue 或联系维护者
恭喜！你的 YouTube 更新通知机器人已成功部署！
现在，你只需编辑 channels.txt 添加频道，机器人就会自动在 每天香港时间 9:00 为你推送新视频！
**已修复**：  
- 目录结构使用 `plaintext` 代码块，确保在 GitHub、VS Code、Typora 等所有平台 **完美对齐显示**  
- 一键复制 → 粘贴 → 保存为 `README.md` 即可

**现在复制整个代码块，粘贴到仓库根目录，命名为 `README.md`**  
你的项目文档立即变得专业、美观、清晰！