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
CHANNELS_FILE = 'channels.txt'

# ==================== 加载频道ID + 名称 ====================
def load_channels():
    if not os.path.exists(CHANNELS_FILE):
        print(f"[警告] {CHANNELS_FILE} 不存在，使用空列表。")
        return []
    
    channels = []
    with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line and not line.startswith('#'):
                parts = line.split('|', 1)  # 以 | 分割 ID 和名称
                channel_id = parts[0].strip()
                channel_name = parts[1].strip() if len(parts) > 1 else None
                channels.append({'id': channel_id, 'name': channel_name})
                print(f"[加载] 频道 {len(channels)}: {channel_id} ({channel_name or '名称待获取'})")
            elif line.startswith('#'):
                print(f"[注释] 行 {line_num}: {line}")
    return channels

# ==================== 获取频道名称（从RSS） ====================
def get_channel_name(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        feed = feedparser.parse(rss_url)
        if not feed.bozo:
            return feed.feed.get('title', '未知频道')
    except Exception as e:
        print(f"[异常] 获取频道 {channel_id} 名称失败: {e}")
    return '未知频道'

# ==================== 状态管理 ====================
def load_state(channels):
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
            print(f"[状态] 加载 state.json，包含 {len(state)} 个频道")
        except Exception as e:
            print(f"[错误] 无法读取 state.json: {e}")
            state = {}
    else:
        print(f"[状态] state.json 不存在，将创建新文件")
    
    for ch in channels:
        cid = ch['id']
        if cid not in state:
            state[cid] = {'last_video_id': None, 'last_published': None}
            print(f"[初始化] 频道 {cid} 状态")
    return state

def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
        print(f"[状态] state.json 已保存")
    except Exception as e:
        print(f"[错误] 保存 state.json 失败: {e}")

# ==================== 频道检测 ====================
def check_channel_id(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        feed = feedparser.parse(rss_url)
        if feed.bozo:
            print(f"[无效] 频道ID {channel_id} 无法访问或RSS解析失败")
            return False
        name = feed.feed.get('title', '未知频道')
        print(f"[有效] 频道ID {channel_id} → {name}")
        return True
    except Exception as e:
        print(f"[异常] 检测频道 {channel_id} 时出错: {e}")
        return False

# ==================== 获取视频 ====================
def get_latest_videos(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        feed = feedparser.parse(rss_url)
        if feed.bozo:
            print(f"[RSS失败] 频道 {channel_id} RSS 解析错误: {feed.bozo_exception}")
            return []
        
        if not feed.entries:
            print(f"[无视频] 频道 {channel_id} RSS 无视频条目")
            return []

        videos = []
        for i, entry in enumerate(feed.entries[:3]):
            try:
                video = {
                    'title': entry.title,
                    'link': entry.link,
                    'video_id': entry.yt_videoid,
                    'description': entry.get('media_description', '') or entry.get('summary', ''),
                    'thumbnail': entry.media_thumbnail[0]['url'] if entry.get('media_thumbnail') else '',
                    'published': entry.published
                }
                videos.append(video)
                if i == 0:
                    print(f"[最新] {channel_id} → {video['title'][:50]}... (ID: {video['video_id']})")
            except Exception as e:
                print(f"[解析错误] 频道 {channel_id} 第 {i+1} 条视频解析失败: {e}")
                continue
        return videos
    except Exception as e:
        print(f"[网络错误] 获取频道 {channel_id} RSS 失败: {e}")
        return []

# ==================== Telegram通知（带频道名称） ====================
def send_telegram_notification(video, channel_name):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[跳过] Telegram 配置缺失")
        return

    # 消息内容（添加频道名称）
    message = (
        f"*新视频更新！*\n"
        f"**频道**：{channel_name}\n\n"
        f"**标题**：{video['title']}\n"
        f"**时间**：{video['published']}\n"
        f"**简介**：{video['description'][:300]}{'...' if len(video['description']) > 300 else ''}"
    )

    # Inline Keyboard：添加“观看视频”按钮
    keyboard = {
        "inline_keyboard": [
            [{"text": "🎥 观看视频", "url": video['link']}]
        ]
    }

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'photo': video['thumbnail'],
        'caption': message,
        'parse_mode': 'Markdown',
        'reply_markup': json.dumps(keyboard)
    }
    try:
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code == 200:
            print(f"[成功] 已发送通知（带按钮）: {video['title'][:40]}...")
        else:
            print(f"[失败] Telegram 返回 {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[异常] 发送 Telegram 通知失败: {e}")

# ==================== 主逻辑 ====================
def check_updates():
    channels = load_channels()
    if not channels:
        print("[退出] 无有效频道ID")
        return

    state = load_state(channels)
    total_updated = 0

    for idx, ch in enumerate(channels, 1):
        channel_id = ch['id']
        channel_name = ch['name'] or get_channel_name(channel_id)  # 如果无名称，自动获取
        print(f"\n{'='*60}")
        print(f"[检查 {idx}/{len(channels)}] 频道: {channel_id} ({channel_name})")
        print(f"{'='*60}")

        videos = get_latest_videos(channel_id)
        if not videos:
            print(f"[跳过] 频道 {channel_id} 无视频数据")
            continue

        latest = videos[0]
        last_id = state[channel_id].get('last_video_id')

        if latest['video_id'] != last_id:
            print(f"[新视频] 发现更新！ID: {latest['video_id']} (原: {last_id})")
            send_telegram_notification(latest, channel_name)  # 传入名称
            state[channel_id] = {
                'last_video_id': latest['video_id'],
                'last_published': latest['published']
            }
            total_updated += 1
        else:
            print(f"[无更新] 最新视频已是已读状态")

    print(f"\n{'-'*60}")
    if total_updated > 0:
        save_state(state)
        print(f"[完成] 本次共 {total_updated} 个频道有更新")
    else:
        print(f"[完成] 所有频道无新视频")

# ==================== 入口 ====================
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '--check-id' and len(sys.argv) > 2:
        check_channel_id(sys.argv[2])
    else:
        check_updates()