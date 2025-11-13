# YouTube 通知器（支持 Shorts + 自动回写）

**每小时自动监控 YouTube 频道更新，推送至 Telegram，支持长视频 & Shorts，带封面、分行、点击直达！**

---

## 功能亮点

| 功能 | 状态 |
|------|------|
| 自动检测 **长视频** 和 **Shorts** | Done |
| 通知 **完美分行 + 完全转义** | Done |
| **频道名称双重回写**（`channels.txt` + `state.json`） | Done |
| **通知失败不更新状态**（防重复） | Done |
| **北京时间显示** | Done |
| **GitHub Actions 每小时运行** | Done |
| **自动清理旧运行记录**（保留最近 2 次） | Done |
| **支持手动触发** | Done |

---

## 仓库结构
youtube-notifier/ ├── main.py                 # 主程序（完整代码） ├── requirements.txt        # Python 依赖 ├── channels.txt            # 频道列表（支持注释） ├── state.json              # 运行时状态（自动生成） └── .github/ └── workflows/ └── update-check.yml  # GitHub Actions 工作流
---

## 部署步骤（3 分钟完成）

### 1. 克隆仓库

```bash
git clone https://github.com/你的用户名/youtube-notifier.git
cd youtube-notifier
2. 配置 channels.txt

格式：频道ID | 频道名称（名称可留空，自动填充）

UCU1RaYhgjlaig3ydjJocINg | 雨落倾城

3. 设置 GitHub Secrets

进入仓库 → Settings → Secrets and variables → Actions
添加以下两个 Secrets：
名称
示例值
TELEGRAM_TOKEN
123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID
-1001234567890

如何获取？

Token：找 @BotFather
Chat ID：将 Bot 拉入群组，发消息后访问 https://api.telegram.org/bot<token>/getUpdates

4. 提交代码
工作流说明（.github/workflows/update-check.yml）
on:
  schedule:
    - cron: '0 * * * *'  # 北京时间每小时整点
  workflow_dispatch:     # 支持手动触发

# 自动清理：只保留最近 2 次运行记录（可修改）
const keep = 2;
修改保留数量：编辑 update-check.yml 中 const keep = 2; 即可

手动触发
进入仓库 → Actions
选择 Check YouTube Updates
点击 Run workflow → Run

常见问题
问题
解决方案
通知不分行
确保使用 MarkdownV2 + \n 换行
400 错误
所有字段已自动转义，无需处理
频道名称不回写
强制回写 fetched_name，自动覆盖
重复通知
通知失败不更新 state.json
时长获取失败
使用正则匹配 lengthSeconds，稳定可靠