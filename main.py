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
CHANNELS_FILE = 'channels.json'  # 新文件：存储频道ID

# ==================== 加载频道ID ====================
def load_channels():
    if not os.path.exists(CHANNELS_FILE):
        print(f"警告: {CHANNELS_FILE} 不存在，使用空列表。")
        return []
    with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('channels', [])

# ==================== 工具函数 ====================

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

def check_channel_id(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    feed = feedparser.parse(rss_url)
    if feed.bozo:
        print(f"频道ID {channel_id} 无效或无法访问。")
        return False
    print(f"频道ID {channel_id} 有效 → {feed.feed.get('title', '未知频道')}")
    return True

def get_latest_videos(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    feed = feedparser.parse(rss_url)
    if feed.bozo:
        print(f"无法获取频道 {channel_id} 的RSS")
        return []

    videos = []
    for entry in feed.entries[:5]:  # 只取最新5条防漏
        video = {
            'title': entry.title,
            'link': entry.link,
            'video_id': entry.yt_videoid,
            'description': entry.get('media_description', '') or entry.get('summary', ''),
            'thumbnail': entry.media_thumbnail[0]['url'] if entry.get('media_thumbnail') else '',
            'published': entry.published  # ISO-8601 格式
        }
        videos.append(video)
    return videos

def parse_iso_time(iso_str):
    """将 ISO-8601 时间转为时间戳（UTC）"""
    try:
        # 处理带时区的情况
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.timestamp()
    except Exception:
        # 备用方案：尝试 RFC-822
        try:
            return time.mktime(time.strptime(iso_str, "%a, %d %b %Y %H:%M:%S %Z"))
        except Exception as e:
            print(f"时间解析失败: {iso_str} - {e}")
            return 0  # 默认0，避免崩溃

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

        # 首次运行或有新视频
        if latest['video_id'] != last_id:
            # 进一步判断时间（防止RSS顺序错乱）
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
                # 首次检测，只通知最新一个
                send_telegram_notification(latest)
                state[channel_id] = {
                    'last_video_id': latest['video_id'],
                    'last_published': latest['