import feedparser
import requests
import json
import os
import sys
import io

# ==================== 配置 ====================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

STATE_FILE = 'state.json'
CHANNELS_FILE = 'channels.txt'

# 1x1 透明像素（作为 document）
TRANSPARENT_PNG = io.BytesIO(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\x2d\x1b\x00\x00\x00\x00IEND\xaeB`\x82')

# ==================== 加载频道 ====================
def load_channels():
    if not os.path.exists(CHANNELS_FILE):
        print(f"[警告] {CHANNELS_FILE} 不存在")
        return []
    channels = []
    with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split('|', 1)
                cid = parts[0].strip()
                name = parts[1].strip() if len(parts) > 1 else None
                channels.append({'id': cid, 'name': name})
    return channels

# ==================== 获取频道名称 ====================
def get_channel_name(channel_id):
    try:
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
        if not feed.bozo and feed.feed:
            return feed.feed.get('title', '未知频道')
    except:
        pass
    return '未知频道'

# ==================== 状态管理 ====================
def load_state(channels):
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except:
            state = {}
    for ch in channels:
        if ch['id'] not in state:
            state[ch['id']] = {'last_video_id': None}
    return state

def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
    except:
        pass

# ==================== 获取最新视频 ====================
def get_latest_videos(channel_id):
    try:
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
        if feed.bozo or not feed.entries:
            return []
        e = feed.entries[0]
        title = e.title.strip() if e.title else "(无标题)"
        thumb_url = e.media_thumbnail[0]['url'] if e.get('media_thumbnail') else None
        if not thumb_url:
            return []
        return [{
            'title': title,
            'link': e.link,
            'video_id': e.yt_videoid,
            'description': e.get('media_description', '') or e.get('summary', ''),
            'thumb_url': thumb_url,
            'published': e.published
        }]
    except Exception as e:
        print(f"[错误] 获取视频失败: {e}")
        return []

# ==================== Telegram 通知：点击封面直接看视频 ====================
def send_telegram_notification(video, channel_name):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    # 下载封面图
    try:
        img_resp = requests.get(video['thumb_url'], timeout=10)
        if img_resp.status_code != 200:
            return
        thumb_file = io.BytesIO(img_resp.content)
        thumb_file.name = "thumb.jpg"
    except:
        return

    # 简介 100 字
    desc = video['description']
    short_desc = (desc[:100] + '…') if len(desc) > 100 else desc

    message = (
        f"*新视频更新！*\n"
        f"**频道**：{channel_name}\n\n"
        f"**标题**：{video['title']}\n"
        f"**时间**：{video['published']}\n"
        f"**简介**：{short_desc}"
    )

    # 使用 multipart/form-data 发送
    files = {
        'thumb': ('thumb.jpg', thumb_file, 'image/jpeg'),
        'document': ('pixel.png', TRANSPARENT_PNG, 'image/png')
    }
    data = {
        'chat_id': TELEGRAM_CHAT_ID,
        'caption': message,
        'parse_mode': 'Markdown'
    }

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument",
            data=data,
            files=files,
            timeout=15
        )
        if r.status_code == 200:
            print(f"[成功] 已发送（点击封面观看）: {video['title'][:30]}")
        else:
            print(f"[失败] {r.status_code}")
    except Exception as e:
        print(f"[异常] {e}")

# ==================== 主逻辑 ====================
def check_updates():
    channels = load_channels()
    if not channels:
        return

    state = load_state(channels)
    updated = False

    for ch in channels:
        cid = ch['id']
        name = ch['name'] or get_channel_name(cid)
        print(f"\n[检查] {cid} ({name})")

        videos = get_latest_videos(cid)
        if not videos:
            continue

        latest = videos[0]
        last_id = state[cid].get('last_video_id')

        if latest['video_id'] != last_id:
            print(f"[新视频] {latest['video_id']}")
            send_telegram_notification(latest, name)
            state[cid]['last_video_id'] = latest['video_id']
            updated = True

    if updated:
        save_state(state)

# ==================== 入口 ====================
if __name__ == "__main__":
    check_updates()