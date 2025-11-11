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

# ==================== 加载频道ID ====================
def load_channels():
    if not os.path.exists(CHANNELS_FILE):
        print(f"[警告] {CHANNELS_FILE} 不存在，使用空列表。")
        return []
    
    channel_ids = []
    with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line and not line.startswith('#'):
                channel_ids.append(line)
                print(f"[加载] 频道 {len(channel_ids)}: {line}")
            elif line.startswith('#'):
                print(f"[注释] 行 {line_num}: {line}")
    return channel_ids

# ==================== 状态管理 ====================
def load_state(channel_ids):
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
    
    for cid in channel_ids:
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
        print(f"[有效] 频道ID {channel_id} → {feed.feed.get('title', '未知频道')}")
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
        for i, entry in enumerate(feed.entries[:3]):  # 只取前3条
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

# ==================== Telegram通知（增强版：添加按钮） ====================
def send_telegram_notification(video):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[跳过] Telegram 配置缺失")
        return

    # 消息内容（Markdown 格式）
    message = (
        f"*新视频更新！*\n\n"
        f"**标题**：{video['title']}\n"
        f"**时间**：{video['published']}\n"
        f"**简介**：{video['description'][:300]}{'...' if len(video['description']) > 300 else ''}"
    )

    # Inline Keyboard：添加“观看视频”按钮（点击跳转 YouTube）
    keyboard = {
        "inline_keyboard": [
            [{"text": "🎥 观看视频", "url": video['link']}]  # URL 按钮，直接打开链接
        ]
    }

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'photo': video['thumbnail'],
        'caption': message,
        'parse_mode': 'Markdown',
        'reply_markup': json.dumps(keyboard)  # 添加按钮 JSON
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
    channel_ids = load_channels()
    if not channel_ids:
        print("[退出] 无有效频道ID")
        return

    state = load_state(channel_ids)
    total_updated = 0

    for idx, channel_id in enumerate(channel_ids, 1):
        print(f"\n{'='*60}")
        print(f"[检查 {idx}/{len(channel_ids)}] 频道: {channel_id}")
        print(f"{'='*60}")

        videos = get_latest_videos(channel_id)
        if not videos:
            print(f"[跳过] 频道 {channel_id} 无视频数据")
            continue

        latest = videos[0]
        last_id = state[channel_id].get('last_video_id')

        if latest['video_id'] != last_id:
            print(f"[新视频] 发现更新！ID: {latest['video_id']} (原: {last_id})")
            send_telegram_notification(latest)
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