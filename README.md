# 🎵 VIP MUSIC BOT

A powerful, feature‑rich **Telegram Music Bot** for voice chats with support for **YouTube, Spotify, Resso, Apple Music, and SoundCloud**, built for performance, scalability, and easy deployment.

---

## 🚀 Overview

**VIP MUSIC BOT** lets you play high‑quality music in Telegram group & channel voice chats with advanced controls, analytics, and multi‑platform support. It is written in **Python** using **Pyrogram** and **Py‑TgCalls**, and supports both **Heroku** and **VPS** deployments.

---

## 🎯 Features

* 🎬 YouTube, Spotify, Resso, Apple Music & SoundCloud support
* 🐍 Written in Python (Pyrogram v2 + Py‑TgCalls)
* ☁️ Heroku & 🖥 VPS deployment support
* 📢 Channel & group voice chat playback
* 🔎 Inline search support
* 🖼 YouTube thumbnail search
* ♾ Unlimited queue system
* 📣 Broadcast messaging
* 📊 Detailed stats & user analytics
* 🚫 Block / Unblock user management
* 🌐 Multi‑language support
* 🎶 Playlist management

---

## ⚡️ Quick Setup

### ☁️ Heroku Deployment

[**![Deploy on Heroku**](https://img.shields.io/badge/Deploy%20On%20Heroku-purple?style=for-the-badge\&logo=heroku)](https://dashboard.heroku.com/new?template=https://github.com/KIRU-OP/VIP-MUSIC)

---

### 🖥 VPS Deployment

```bash
# Clone the repository
git clone https://github.com/KIRU-OP/VIP-MUSIC && cd VIP-MUSIC

# Run setup script
bash setup
```

```bash
# Configure environment variables
nano .env
# Save with CTRL + X → Y → Enter
```

```bash
# Install tmux
sudo apt update && sudo apt install tmux -y

# Start tmux session
tmux

# Run the bot
bash start
```

🔹 Exit tmux session (bot keeps running): **Ctrl + B → D**

---

## ⚙️ Configuration Variables

### 🔴 Required Variables

* `API_ID` – Telegram API ID (from my.telegram.org)
* `API_HASH` – Telegram API Hash
* `BOT_TOKEN` – Bot token from @BotFather
* `MONGO_DB_URI` – MongoDB database URL
* `LOG_GROUP_ID` – Telegram group ID for logs
* `OWNER_ID` – Your Telegram user ID
* `STRING_SESSION` – Pyrogram v2 string session

---

### 🟢 Optional Variables

* `SPOTIFY_CLIENT_ID` – Spotify developer client ID
* `SPOTIFY_CLIENT_SECRET` – Spotify developer client secret
* `HEROKU_API_KEY` – Heroku API key
* `HEROKU_APP_NAME` – Heroku app name

📘 [**Full variable list**](https://github.com/KIRU-OP/VIP-MUSIC/edit/Test/README.md)

---

⚠️ Make sure the API is **enabled** for your project, otherwise YouTube search will not work.

---

## 🤝 Support & Community

* 🔔 [**Updates Channel**](https://t.me/about_deadly_venom)
* 🆘 [**Support Group**](https://t.me/TNOBITA_SUPPORT)

---

## 📃 License

This project is licensed under the [**MIT License**](https://github.com/KIRU-OP/VIP-MUSIC/edit/Test/README.md)

---

## 🙋‍♂️ Credits

* 👑 ** KIRU ** – Project Owner & Developer

---

## 🙏 Special Thanks

A heartfelt thanks to **VIP MUSIC** ❤️

* [**GitHub**]()
* [**Project**]()

This project is inspired by YukkiMusicBot and customized with additional features, optimizations, and Google Cloud YouTube API integration.

---

✨ **Made with ❤️ for Telegram Music Lovers** ✨
