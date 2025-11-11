import feedparser
import requests
import json
import os
import sys
import time
from datetime import datetime

# 配置：替换为你的Telegram Bot Token和Chat ID
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')  # 从环境变量获取
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')  # 从环境变量获取

# 状态文件路径（在GitHub仓库中）
STATE_FILE = 'state.json'

# 加载状态（上次视频ID和发布时间）
def load_state(channel_ids):
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
    else:
        state = {}
    for channel_id in channel_ids:
        if channel_id not in state:
            state[channel_id] = {'last_video_id': None, 'last_published': None}
    return state

# 保存状态
def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=4)

# 检测频道ID是否有效
def check_channel_id(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    feed = feedparser.parse(rss_url)
    if feed.bozo:  # 如果解析失败
        print(f"频道ID {channel_id} 无效或不存在。")
        return False
    else:
        print(f"频道ID {channel_id} 有效。频道名称: {feed.feed.title}")
        return True

# 获取最新视频
def get_latest_videos(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    feed = feedparser.parse(rss_url)
    if feed.bozo:
        return None
    videos = []
    for entry in feed.entries:
        video = {
            'title': entry.title,
            'link': entry.link,
            'published': entry.published,  # RFC 822格式时间
            'description': entry.description,
            'thumbnail': entry.media_thumbnail[0]['url'] if 'media_thumbnail' in entry else '',
            'video_id': entry.yt_videoid
        }
        videos.append(video)
    return videos

# 发送Telegram通知
def send_telegram_notification(video):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram Token或Chat ID未配置，无法发送通知。")
        return

    message = (
        f"视频更新时间: {video['published']}\n"
        f"视频名称: {video['title']}\n"
        f"视频介绍: {video['description'][:200]}...\n"  # 截取介绍，避免太长
        f"视频链接: {video['link']}"
    )
    
    # 发送图片（封面）+文本
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'photo': video['thumbnail'],
        'caption': message
    }
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        print(f"通知发送成功: {video['title']}")
    else:
        print(f"通知发送失败: {response.text}")

# 主函数：检查更新
def check_updates(channel_ids):
    state = load_state(channel_ids)
    for channel_id in channel_ids:
        videos = get_latest_videos(channel_id)
        if not videos:
            print(f"无法获取频道 {channel_id} 的视频。")
            continue
        
        latest_video = videos[0]  # RSS按时间降序，第一条是最新的
        last_published = state[channel_id]['last_published']
        last_video_id = state[channel_id]['last_video_id']
        
        # 解析时间为UTC时间戳比较
        latest_time = time.mktime(time.strptime(latest_video['published'], "%a, %d %b %Y %H:%M:%S %Z"))
        if last_published:
            last_time = time.mktime(time.strptime(last_published, "%a, %d %b %Y %H:%M:%S %Z"))
        else:
            last_time = 0
        
        if latest_video['video_id'] != last_video_id and latest_time > last_time:
            print(f"检测到新视频: {latest_video['title']}")
            send_telegram_notification(latest_video)
            state[channel_id]['last_video_id'] = latest_video['video_id']
            state[channel_id]['last_published'] = latest_video['published']
    
    save_state(state)

if __name__ == "__main__":
    # 示例频道ID列表（可配置多个）
    channel_ids = ['UC_x5XG1OV2P6uZZ5FSM9Ttw', '另一个频道ID']  # 替换为实际ID
    
    if len(sys.argv) > 1 and sys.argv[1] == '--check-id':
        if len(sys.argv) > 2:
            check_channel_id(sys.argv[2])
        else:
            print("请提供频道ID，例如: python main.py --check-id UC_x5XG1OV2P6uZZ5FSM9Ttw")
    else:
        check_updates(channel_ids)