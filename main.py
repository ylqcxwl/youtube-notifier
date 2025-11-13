#!/usr/bin/env python3
import feedparser
import requests
import json
import os
import sys
from datetime import datetime
import pytz
import re

# ==================== 配置 ====================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

STATE_FILE = 'state.json'
CHANNELS_FILE = 'channels.txt'

# 北京时间时区
BEIJING_TZ = pytz.timezone('Asia/Shanghai')

# ==================== 加载频道（保留原始行） ====================
def load_channels():
    print(f"[加载] 正在读取 {CHANNELS_FILE}...")
    if not os.path.exists(CHANNELS_FILE):
        print(f"[错误] {CHANNELS_FILE} 不存在！")
        return [], []

    channels = []
    original_lines = []
    with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
        original_lines = f.readlines()

    for line_num, raw_line in enumerate(original_lines, 1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith('#'):
            if stripped.startswith('#'):
                print(f"[注释] 行 {line_num}: {stripped}")
            continue
        try:
            parts = stripped.split('|', 1)
            cid = parts[0].strip()
            name_part = parts[1].strip() if len(parts) > 1 else ''
            name = name_part if name_part else None
            channels.append({
                'id': cid,
                'name': name,
                'line_num': line_num,
                'raw_line': raw_line,
                'stripped': stripped,
                'fetched_name': None
            })
            print(f"[加载] 频道 {len(channels)}: {cid} ({name or '待获取'})")
        except Exception as e:
            print(f"[错误] 行 {line_num} 解析失败: {stripped} → {e}")
    print(f"[完成] 共加载 {len(channels)} 个频道")
    return channels, original_lines

# ==================== 强制回写频道名称到 channels.txt ====================
def save_channel_name_to_file(channels, original_lines):
    if not channels or not original_lines:
        return False

    updated = False
    new_lines = original_lines[:]

    for ch in channels:
        if ch.get('fetched_name'):
            cid = ch['id']
            fetched_name = ch['fetched_name']
            line_idx = ch['line_num'] - 1
            new_line = f"{cid} | {fetched_name}\n"
            new_lines[line_idx] = new_line
            print(f"[文件回写] {cid} → {fetched_name}")
            updated = True

    if updated:
        try:
            with open(CHANNELS_FILE, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            print(f"[文件] {CHANNELS_FILE} 已强制更新")
            return True
        except Exception as e:
            print(f"[错误] 文件回写失败: {e}")
    return updated

# ==================== 加载/更新 state.json ====================
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
        print(f"[状态] {STATE_FILE} 不存在，将创建新文件")

    for ch in channels:
        cid = ch['id']
        if cid not in state:
            state[cid] = {
                'last_video_id': None,
                'last_shorts_id': None,
                'channel_name': None
            }
        if state[cid].get('channel_name') and not ch['name']:
            ch['name'] = state[cid]['channel_name']
            print(f"[缓存] 从 state.json 恢复名称: {ch['name']}")

    return state

def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
        print(f"[状态] state.json 已保存")
    except Exception as e:
        print(f"[错误] 保存 state.json 失败: {e}")

# ==================== 获取频道名称（强制回写） ====================
def get_channel_name(channel_id, channel_obj, state):
    cid = channel_id
    if channel_obj['name']:
        print(f"[缓存] 使用 channels.txt 名称: {channel_obj['name']}")
        if state[cid].get('channel_name') != channel_obj['name']:
            state[cid]['channel_name'] = channel_obj['name']
        return channel_obj['name']

    if state[cid].get('channel_name'):
        name = state[cid]['channel_name']
        print(f"[缓存] 使用 state.json 名称: {name}")
        channel_obj['name'] = name
        return name

    try:
        print(f"[RSS] 正在获取频道名称: {cid}")
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
        if feed.bozo:
            print(f"[RSS失败] 解析错误: {getattr(feed, 'bozo_exception', '未知')}")
            return '未知频道'
        if feed.feed and feed.feed.get('title'):
            name = feed.feed.title.strip()
            if name:
                print(f"[成功] 获取到名称: {name}")
                state[cid]['channel_name'] = name
                channel_obj['fetched_name'] = name
                channel_obj['name'] = name
                return name
        return '未知频道'
    except Exception as e:
        print(f"[异常] 获取名称失败: {e}")
        return '未知频道'

# ==================== 时间转换 ====================
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

# ==================== 获取视频时长 ====================
def get_video_duration(video_id):
    try:
        print(f"[时长] 正在获取视频时长: {video_id}")
        url = f"https://www.youtube.com/watch?v={video_id}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        
        match = re.search(r'"lengthSeconds":"(\d+)"', resp.text)
        if match:
            duration = int(match.group(1))
            print(f"[时长成功] {duration} 秒")
            return duration
        return None
    except:
        return None

# ==================== 获取最新视频 ====================
def get_latest_videos(channel_id):
    print(f"[RSS] 正在获取频道视频: {channel_id}")
    try:
        feed = feedparser.parse(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
        if feed.bozo or not feed.entries:
            return None
        
        e = feed.entries[0]
        title = e.title.strip() if e.title else "(无标题)"
        thumb_url = e.media_thumbnail[0]['url'] if e.get('media_thumbnail') else None
        desc = e.get('media_description', '') or e.get('summary', '')
        pub_beijing = to_beijing_time(e.published)
        video_id = e.yt_videoid
        
        duration = get_video_duration(video_id)
        feed_type = 'Shorts' if duration and duration < 60 else '视频'
        
        print(f"[最新] 标题: {title}")
        print(f"[最新] 视频ID: {video_id}")
        print(f"[最新] 类型: {feed_type}")
        print(f"[最新] 发布时间: {pub_beijing}")
        
        return {
            'title': title,
            'link': e.link,
            'video_id': video_id,
            'description': desc,
            'thumb_url': thumb_url,
            'published_beijing': pub_beijing,
            'feed_type': feed_type
        }
    except Exception as e:
        print(f"[网络错误] 获取视频失败: {e}")
        return None

# ==================== Telegram 通知（完美分行 + 完全转义） ====================
def send_telegram_notification(video, channel_name):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    def escape(text):
        if not text:
            return ""
        return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))

    title = escape(video['title'].strip())
    channel = escape(channel_name.strip())
    desc = escape(video['description'][:97].strip() + ('...' if len(video['description']) > 97 else ''))
    pub_time = video['published_beijing']
    link = video['link']
    feed_type = video['feed_type']

    message = (
        f"*频道*：{channel}\n"
        f"\n"
        f"[{title}]({link})\n"
        f"*类型*：{feed_type}\n"
        f"*简介*：{desc}\n"
        f"*时间*：{pub_time}"
    )

    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'parse_mode': 'MarkdownV2'
    }

    if video['thumb_url']:
        payload['photo'] = video['thumb_url']
        payload['caption'] = message
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    else:
        payload['text'] = message
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        print(f"[通知] 正在发送 {feed_type} 通知...")
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code == 200:
            print(f"[成功] 通知已发送")
            return True
        else:
            print(f"[失败] {r.status_code}: {r.text}")
            return False
    except Exception as e:
        print(f"[异常] 发送失败: {e}")
        return False

# ==================== 主逻辑 ====================
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
    file_updated = False

    for idx, ch in enumerate(channels, 1):
        cid = ch['id']
        print(f"\n{'='*60}")
        print(f"  [频道 {idx}/{len(channels)}] 日志开始 - ID: {cid}")
        print(f"{'='*60}")

        name = get_channel_name(cid, ch, state)
        print(f"[频道] 最终名称: {name}")

        video = get_latest_videos(cid)
        if video is None:
            print(f"[跳过] 无视频或获取失败")
            print(f"{'='*60}")
            print(f"  [频道 {idx}/{len(channels)}] 日志结束")
            print(f"{'='*60}\n")
            continue

        state_key = 'last_shorts_id' if video['feed_type'] == 'Shorts' else 'last_video_id'
        last_id = state[cid].get(state_key)

        if video['video_id'] != last_id:
            print(f"[新{video['feed_type']}] 发现更新！ID: {video['video_id']}")
            if send_telegram_notification(video, name):
                state[cid][state_key] = video['video_id']
                total_updated += 1
                print(f"[状态] 已更新 {state_key}")
            else:
                print(f"[跳过] 通知失败，状态未更新")
        else:
            print(f"[无更新] {video['feed_type']} 已通知")

        print(f"{'='*60}")
        print(f"  [频道 {idx}/{len(channels)}] 日志结束")
        print(f"{'='*60}\n")

    if save_channel_name_to_file(channels, original_lines):
        file_updated = True

    save_state(state)

    print(f"[完成] 本次共 {total_updated} 个更新")
    if file_updated:
        print(f"[文件] channels.txt 已强制更新")

# ==================== 入口 ====================
if __name__ == "__main__":
    check_updates()