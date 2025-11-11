import feedparser
import requests
import json
import os
import sys

# ==================== 配置 ====================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

STATE_FILE = 'state.json'
CHANNELS_FILE = 'channels.txt'

# ==================== 加载频道（详细日志） ====================
def load_channels():
    print(f"[加载] 正在读取 {CHANNELS_FILE}...")
    if not os.path.exists(CHANNELS_FILE):
        print(f"[错误] {CHANNELS_FILE} 不存在！")
        return []
    
    channels = []
    with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                if line.startswith('#'):
                    print(f"[注释] 行 {line_num}: {line}")
                continue
            try:
                parts = line.split('|', 1)
                cid = parts[0].strip()
                name = parts[1].strip() if len(parts) > 1 else None
                channels.append({'id': cid, 'name': name})
                print(f"[加载] 频道 {len(channels)}: {cid} ({name or '自动获取'})")
            except Exception as e:
                print(f"[错误] 行 {line_num} 解析失败: {line} → {e}")
    print(f"[完成] 共加载 {len(channels)} 个频道")
    return channels

# ==================== 获取频道名称（容错） ====================
def get_channel_name(channel_id):
    try:
        print(f"[RSS] 正在获取频道名称: {channel_id}")
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
        if feed.bozo:
            print(f"[RSS失败] 频道 {channel_id} 解析错误: {getattr(feed, 'bozo_exception', '未知')}")
            return '未知频道'
        if feed.feed and feed.feed.get('title'):
            name = feed.feed.title
            print(f"[成功] 频道名称: {name}")
            return name
        else:
            print(f"[无名称] 频道 {channel_id} RSS 无 title")
            return '未知频道'
    except Exception as e:
        print(f"[异常] 获取频道 {channel_id} 名称失败: {e}")
        return '未知频道'

# ==================== 状态管理（详细日志） ====================
def load_state(channels):
    print(f"[状态] 正在加载 {STATE_FILE}...")
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
            print(f"[状态] 成功加载，包含 {len(state)} 个频道记录")
        except Exception as e:
            print(f"[错误] 读取 state.json 失败: {e} → 使用空状态")
            state = {}
    else:
        print(f"[状态] {STATE_FILE} 不存在，将创建新文件")
    
    for ch in channels:
        cid = ch['id']
        if cid not in state:
            state[cid] = {'last_video_id': None}
            print(f"[初始化] 频道 {cid} 状态")
    return state

def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
        print(f"[状态] state.json 已保存")
    except Exception as e:
        print(f"[错误] 保存 state.json 失败: {e}")

# ==================== 获取最新视频（独立容错） ====================
def get_latest_videos(channel_id):
    print(f"[RSS] 正在获取频道视频: {channel_id}")
    try:
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
        if feed.bozo:
            print(f"[RSS失败] 频道 {channel_id} 解析错误: {getattr(feed, 'bozo_exception', '未知')}")
            return []
        if not feed.entries:
            print(f"[无视频] 频道 {channel_id} RSS 为空")
            return []
        
        e = feed.entries[0]
        title = e.title.strip() if e.title else "(无标题)"
        thumb_url = e.media_thumbnail[0]['url'] if e.get('media_thumbnail') else None
        if not thumb_url:
            print(f"[无封面] 频道 {channel_id} 视频无缩略图")
            return []
        
        print(f"[最新] 视频标题: {title}")
        print(f"[最新] 视频ID: {e.yt_videoid}")
        return [{
            'title': title,
            'link': e.link,
            'video_id': e.yt_videoid,
            'description': e.get('media_description', '') or e.get('summary', ''),
            'thumb_url': thumb_url,
            'published': e.published
        }]
    except Exception as e:
        print(f"[网络错误] 获取 {channel_id} 视频失败: {e}")
        return []

# ==================== Telegram 通知（点击标题播放） ====================
def send_telegram_notification(video, channel_name):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[跳过] Telegram 配置缺失")
        return

    desc = video['description']
    short_desc = (desc[:100] + '…') if len(desc) > 100 else desc
    title_link = f"[{video['title']}]({video['link']})"

    message = (
        f"**频道**：{channel_name}\n\n"
        f"{title_link}\n"
        f"**简介**：{short_desc}\n"
        f"**时间**：{video['published']}"
    )

    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'photo': video['thumb_url'],
        'caption': message,
        'parse_mode': 'Markdown'
    }

    try:
        print(f"[通知] 正在发送通知...")
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
            data=payload,
            timeout=15
        )
        if r.status_code == 200:
            print(f"[成功] 通知已发送")
        else:
            print(f"[失败] Telegram 返回 {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[异常] 发送通知失败: {e}")

# ==================== 主逻辑（每个频道独立） ====================
def check_updates():
    print(f"\n{'='*60}")
    print(f"  YouTube 通知器启动 - 香港时间 {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')} HKT")
    print(f"{'='*60}\n")

    channels = load_channels()
    if not channels:
        print("[退出] 无有效频道配置")
        return

    state = load_state(channels)
    total_updated = 0

    for idx, ch in enumerate(channels, 1):
        cid = ch['id']
        name = ch['name'] or get_channel_name(cid)
        print(f"\n{'-'*50}")
        print(f"[检查 {idx}/{len(channels)}] 频道: {cid} ({name})")
        print(f"{'-'*50}")

        videos = get_latest_videos(cid)
        if not videos:
            print(f"[跳过] 无新视频或获取失败")
            continue

        latest = videos[0]
        last_id = state[cid].get('last_video_id')

        if latest['video_id'] != last_id:
            print(f"[新视频] 发现更新！ID: {latest['video_id']}")
            send_telegram_notification(latest, name)
            state[cid]['last_video_id'] = latest['video_id']
            total_updated += 1
        else:
            print(f"[无更新] 最新视频已通知")

    print(f"\n{'='*60}")
    if total_updated > 0:
        save_state(state)
        print(f"[完成] 本次共 {total_updated} 个频道有更新")
    else:
        print(f"[完成] 所有频道无新视频")
    print(f"{'='*60}\n")
 
# ==================== 入口 ====================
if __name__ == "__main__":
    check_updates()