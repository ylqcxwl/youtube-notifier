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
                'stripped': stripped
            })
            print(f"[加载] 频道 {len(channels)}: {cid} ({name or '待获取'})")
        except Exception as e:
            print(f"[错误] 行 {line_num} 解析失败: {stripped} → {e}")
    print(f"[完成] 共加载 {len(channels)} 个频道")
    return channels, original_lines

# ==================== 回写频道名称到 channels.txt ====================
def save_channel_name_to_file(channels, original_lines):
    if not channels or not original_lines:
        return False

    updated = False
    new_lines = original_lines[:]

    for ch in channels:
        if ch['name'] is None and ch.get('fetched_name'):
            cid = ch['id']
            fetched_name = ch['fetched_name']
            line_idx = ch['line_num'] - 1
            new_line = f"{cid} | {fetched_name}\n"
            old_line = new_lines[line_idx].strip()

            if '|' in old_line:
                after_pipe = old_line.split('|', 1)[1].strip()
                if not after_pipe:
                    new_lines[line_idx] = new_line
                    print(f"[文件回写] {cid} → {fetched_name}")
                    updated = True

    if updated:
        try:
            with open(CHANNELS_FILE, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            print(f"[文件] {CHANNELS_FILE} 已更新")
            return True
        except Exception as e:
            print(f"[错误] 文件回写失败: {e}")
    return updated

# ==================== 加载/更新 state.json（包含频道名称） ====================
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
                'last_shorts_id': None,  # 新增 Shorts 状态
                'channel_name': None
            }
            print(f"[初始化] 频道 {cid} 状态（视频 + Shorts）")
        if state[cid].get('channel_name') and not ch['name']:
            ch['name'] = state[cid]['channel_name']
            print(f"[缓存] 从 state.json 恢复名称: {ch['name']}")

    return state

def save_state(state):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4, ensure_ascii=False)
        print(f"[状态] state.json 已保存（含名称 + Shorts 状态）")
    except Exception as e:
        print(f"[错误] 保存 state.json 失败: {e}")

# ==================== 获取频道名称 ====================
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
        print(f"[无名称] RSS 无 title")
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

# ==================== 获取最新视频/Shorts ====================
def get_latest_videos(channel_id, feed_type='video'):
    print(f"[RSS] 正在获取 {feed_type} 视频: {channel_id}")
    try:
        if feed_type == 'shorts':
            # Shorts RSS: 频道 Shorts 播放列表
            playlist_id = f"UL{channel_id[2:]}"
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}&playlist_id={playlist_id}"
        else:
            rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        
        feed = feedparser.parse(rss_url)
        if feed.bozo:
            print(f"[RSS失败] {feed_type} 解析错误: {getattr(feed, 'bozo_exception', '未知')}")
            return None
        if not feed.entries:
            print(f"[无{feed_type}] RSS 为空")
            return None
        
        e = feed.entries[0]
        title = e.title.strip() if e.title else "(无标题)"
        thumb_url = e.media_thumbnail[0]['url'] if e.get('media_thumbnail') else None
        desc = e.get('media_description', '') or e.get('summary', '')
        pub_beijing = to_beijing_time(e.published)
        
        print(f"[最新{feed_type}] 标题: {title}")
        print(f"[最新{feed_type}] 视频ID: {e.yt_videoid}")
        print(f"[最新{feed_type}] 缩略图: {thumb_url or '无'}")
        print(f"[最新{feed_type}] 发布时间: {pub_beijing}")
        
        return {
            'title': title,
            'link': e.link,
            'video_id': e.yt_videoid,
            'description': desc,
            'thumb_url': thumb_url,
            'published_beijing': pub_beijing
        }
    except Exception as e:
        print(f"[网络错误] 获取 {feed_type} 失败: {e}")
        return None

# ==================== Telegram 通知（区分视频/Shorts） ====================
def send_telegram_notification(video, channel_name, feed_type='video'):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[跳过] Telegram 配置缺失")
        return

    desc = video['description']
    short_desc = (desc[:100] + '...') if len(desc) > 100 else desc
    title_link = f"[{video['title']}]({video['link']})"
    type_label = f"**类型**：{feed_type}"

    message = (
        f"**频道**：{channel_name}\n\n"
        f"{title_link}\n"
        f"{type_label}\n"
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
        print(f"[通知] 正在发送 {feed_type} 通知...")
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code == 200:
            print(f"[成功] {feed_type} 通知已发送")
        else:
            print(f"[失败] {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[异常] {feed_type} 发送失败: {e}")

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

    for idx, ch in enumerate(channels, 1):
        cid = ch['id']
        print(f"\n{'='*60}")
        print(f"  [频道 {idx}/{len(channels)}] 日志开始 - ID: {cid}")
        print(f"{'='*60}")

        name = get_channel_name(cid, ch, state)
        print(f"[频道] 最终名称: {name}")

        # 检查常规视频
        print(f"\n[子检查] 常规视频")
        video = get_latest_videos(cid, 'video')
        if video is not None:
            last_id = state[cid].get('last_video_id')
            if video['video_id'] != last_id:
                print(f"[新视频] 发现常规更新！ID: {video['video_id']}")
                send_telegram_notification(video, name, '视频')
                state[cid]['last_video_id'] = video['video_id']
                total_updated += 1
            else:
                print(f"[无更新] 常规视频已通知")
        else:
            print(f"[跳过] 常规视频获取失败")

        # 检查 Shorts
        print(f"\n[子检查] Shorts")
        shorts = get_latest_videos(cid, 'shorts')
        if shorts is not None:
            last_shorts_id = state[cid].get('last_shorts_id')
            if shorts['video_id'] != last_shorts_id:
                print(f"[新Shorts] 发现 Shorts 更新！ID: {shorts['video_id']}")
                send_telegram_notification(shorts, name, 'Shorts')
                state[cid]['last_shorts_id'] = shorts['video_id']
                total_updated += 1
            else:
                print(f"[无更新] Shorts 已通知")
        else:
            print(f"[跳过] Shorts 获取失败")

        print(f"{'='*60}")
        print(f"  [频道 {idx}/{len(channels)}] 日志结束")
        print(f"{'='*60}\n")

    # 回写文件
    save_channel_name_to_file(channels, original_lines)

    # 保存状态（含名称 + Shorts ID）
    save_state(state)

    print(f"[完成] 本次共 {total_updated} 个更新（视频 + Shorts）")

# ==================== 入口 ====================
if __name__ == "__main__":
    check_updates()