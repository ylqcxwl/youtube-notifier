#!/usr/bin/env python3
import feedparser
import requests
import json
import os
import sys
from datetime import datetime
import pytz

# ==================== 配置 ====================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

STATE_FILE = 'state.json'
CHANNELS_FILE = 'channels.txt'

# 北京时间时区
BEIJING_TZ = pytz.timezone('Asia/Shanghai')

# ==================== 加载频道（详细日志） ====================
def load_channels():
    print(f"[加载] 正在读取 {CHANNELS_FILE}...")
    if not os.path.exists(CHANNELS_FILE):
        print(f"[错误] {CHANNELS_FILE} 不存在！")
        return []
    
    channels = []
    with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('#'):
            if line.startswith('#'):
                print(f"[注释] 行 {line_num}: {line}")
            continue
        try:
            parts = line.split('|', 1)
            cid = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else None
            channels.append({'id': cid, 'name': name, 'line_num': line_num, 'raw_line': line})
            print(f"[加载] 频道 {len(channels)}: {cid} ({name or '自动获取'})")
        except Exception as e:
            print(f"[错误] 行 {line_num} 解析失败: {line} → {e}")
    print(f"[完成] 共加载 {len(channels)} 个频道")
    return channels, lines

# ==================== 回写频道名称到 channels.txt ====================
def save_channel_name(channels, original_lines):
    updated = False
    new_lines = original_lines[:]
    for ch in channels:
        if ch['name'] is None and ch.get('fetched_name'):
            cid = ch['id']
            new_line = f"{cid} | {ch['fetched_name']}\n"
            new_lines[ch['line_num'] - 1] = new_line
            print(f"[回写] 频道 {cid} 名称已写入: {ch['fetched_name']}")
            updated = True
    if updated:
        try:
            with open(CHANNELS_FILE, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            print(f"[回写] {CHANNELS_FILE} 已更新")
        except Exception as e:
            print(f"[错误] 回写 {CHANNELS_FILE} 失败: {e}")

# ==================== 获取频道名称（容错 + 回写） ====================
def get_channel_name(channel_id, channel_obj):
    if channel_obj['name']:
        print(f"[缓存] 使用已有名称: {channel_obj['name']}")
        return channel_obj['name']
    
    try:
        print(f"[RSS] 正在获取频道名称: {channel_id}")
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
        if feed.bozo:
            print(f"[RSS失败] 解析错误: {getattr(feed, 'bozo_exception', '未知')}")
            return '未知频道'
        if feed.feed and feed.feed.get('title'):
            name = feed.feed.title.strip()
            print(f"[成功] 获取到频道名称: {name}")
            channel_obj['fetched_name'] = name  # 标记用于回写
            return name
        else:
            print(f"[无名称] RSS 无 title")
            return '未知频道'
    except Exception as e:
        print(f"[异常] 获取名称失败: {e}")
        return '未知频道'

# ==================== 状态管理 ====================
def load_state(channels):
    print(f"[状态] 正在加载 {STATE_FILE}...")
    state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
            print(f"[状态] 成功加载，包含 {len(state)} 个记录")
        except Exception as e:
            print(f"[错误] 读取 state.json 失败: {e}")
            state = {}
    else:
        print(f"[状态] {STATE_FILE} 不存在，将创建")
    
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

# ==================== 时间转换：UTC → 北京时间 ====================
def to_beijing_time(iso_time_str):
    try:
        utc_dt = datetime.strptime(iso_time_str, "%a, %d %b %Y %H:%M:%S %Z")
        if utc_dt.tzinfo is None:
            utc_dt = pytz.utc.localize(utc_dt)
        return utc_dt.astimezone(BEIJING_TZ).strftime("%Y年%m月%d日 %H:%M")
    except:
        try:
            utc_dt = datetime.fromisoformat(iso_time_str.replace('Z', '+00:00'))
            return utc_dt.astimezone(BEIJING_TZ).strftime("%Y年%m月%d日 %H:%M")
        except:
            return iso_time_str

# ==================== 获取最新视频（独立容错） ====================
def get_latest_videos(channel_id):
    print(f"[RSS] 正在获取视频: {channel_id}")
    try:
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
        if feed.bozo:
            print(f"[RSS失败] 解析错误: {getattr(feed, 'bozo_exception', '未知')}")
            return None
        if not feed.entries:
            print(f"[无视频] RSS 为空")
            return None
        
        e = feed.entries[0]
        title = e.title.strip() if e.title else "(无标题)"
        thumb_url = e.media_thumbnail[0]['url'] if e.get('media_thumbnail') else None
        desc = e.get('media_description', '') or e.get('summary', '')
        pub_beijing = to_beijing_time(e.published)
        
        print(f"[最新] 标题: {title}")
        print(f"[最新] 视频ID: {e.yt_videoid}")
        print(f"[最新] 缩略图: {thumb_url or '无'}")
        print(f"[最新] 简介长度: {len(desc)} 字")
        print(f"[最新] 发布时间: {pub_beijing}")
        
        return {
            'title': title,
            'link': e.link,
            'video_id': e.yt_videoid,
            'description': desc,
            'thumb_url': thumb_url,
            'published_beijing': pub_beijing
        }
    except Exception as e:
        print(f"[网络错误] 获取视频失败: {e}")
        return None

# ==================== Telegram 通知 ====================
def send_telegram_notification(video, channel_name):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[跳过] Telegram 配置缺失")
        return

    desc = video['description']
    short_desc = (desc[:100] + '...') if len(desc) > 100 else desc
    title_link = f"[{video['title']}]({video['link']})"

    message = (
        f"**频道**：{channel_name}\n\n"
        f"{title_link}\n"
        f"**简介**：{short_desc}\n"
        f"**时间**：{video['published_beijing']}"
    )

    if video['thumb_url']:
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'photo': video['thumb_url'],
            'caption': message,
            'parse_mode': 'Markdown'
        }
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    else:
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'Markdown'
        }
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        print(f"[通知] 正在发送...")
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code == 200:
            print(f"[成功] 通知已发送")
        else:
            print(f"[失败] {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[异常] 发送失败: {e}")

# ==================== 主逻辑（每个频道独立日志块） ====================
def check_updates():
    print(f"\n{'='*60}")
    now_beijing = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
    print(f"  YouTube 通知器启动 - 北京时间 {now_beijing}")
    print(f"{'='*60}\n")

    channels_data = load_channels()
    if not channels_data:
        return
    channels, original_lines = channels_data

    if not channels:
        print("[退出] 无有效频道")
        return

    state = load_state(channels)
    total_updated = 0

    for idx, ch in enumerate(channels, 1):
        cid = ch['id']
        print(f"\n{'='*60}")
        print(f"  [频道 {idx}/{len(channels)}] 日志开始 - ID: {cid}")
        print(f"{'='*60}")

        name = get_channel_name(cid, ch)
        print(f"[频道] 名称: {name}")

        video = get_latest_videos(cid)
        if video is None:
            print(f"[跳过] 无视频或获取失败")
        else:
            last_id = state[cid].get('last_video_id')
            if video['video_id'] != last_id:
                print(f"[新视频] 发现更新！ID: {video['video_id']}")
                send_telegram_notification(video, name)
                state[cid]['last_video_id'] = video['video_id']
                total_updated += 1
            else:
                print(f"[无更新] 已通知过")

        print(f"{'='*60}")
        print(f"  [频道 {idx}/{len(channels)}] 日志结束")
        print(f"{'='*60}\n")

    # 回写频道名称
    save_channel_name(channels, original_lines)

    if total_updated > 0:
        save_state(state)
        print(f"[完成] 本次共 {total_updated} 个频道有更新")
    else:
        print(f"[完成] 所有频道无新视频")

# ==================== 入口 ====================
if __name__ == "__main__":
    check_updates()