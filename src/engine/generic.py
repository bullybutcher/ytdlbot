#!/usr/bin/env python3
# coding: utf-8

# ytdlbot - generic.py

import logging
import os
import random
import shutil
from pathlib import Path

import yt_dlp

from config import AUDIO_FORMAT, PROXY_FILE
from utils import is_youtube
from utils.trimming import estimate_file_size_mb, extract_trimmed_duration
from database.model import get_format_settings, get_quality_settings
from engine.base import BaseDownloader
from proxy import get_proxy, load_proxies, construct_proxy_string, update_proxies


def match_filter(info_dict):
    if info_dict.get("is_live"):
        raise NotImplementedError("Skipping live video")
    return None  # Allow download for non-live videos


class YoutubeDownload(BaseDownloader):
    @staticmethod
    def get_format(m):
        return [
            f"bestvideo[ext=mp4][height={m}]+bestaudio[ext=m4a]",
            f"bestvideo[vcodec^=avc][height={m}]+bestaudio[acodec^=mp4a]/best[vcodec^=avc]/best",
        ]

    def _setup_formats(self) -> list | None:
        if not is_youtube(self._url):
            return [None]

        quality, format_ = get_quality_settings(self._chat_id), get_format_settings(self._chat_id)
        # quality: high, medium, low, custom
        # format: audio, video, document
        formats = []
        defaults = [
            # webm , vp9 and av01 are not streamable on telegram, so we'll extract only mp4
            "bestvideo[ext=mp4][vcodec!*=av01][vcodec!*=vp09]+bestaudio[ext=m4a]/bestvideo+bestaudio",
            "bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/best[vcodec^=avc]/best",
            None,
        ]
        audio = AUDIO_FORMAT or "m4a"
        maps = {
            "high-audio": [f"bestaudio[ext={audio}]"],
            "high-video": defaults,
            "high-document": defaults,
            "medium-audio": [f"bestaudio[ext={audio}]"],  # no mediumaudio :-(
            "medium-video": self.get_format(720),
            "medium-document": self.get_format(720),
            "low-audio": [f"bestaudio[ext={audio}]"],
            "low-video": self.get_format(480),
            "low-document": self.get_format(480),
            "custom-audio": "",
            "custom-video": "",
            "custom-document": "",
        }

        if quality == "custom":
            pass
            # TODO not supported yet
            # get format from ytdlp, send inlinekeyboard button to user so they can choose
            # another callback will be triggered to download the video
            # available_options = {
            #     "480P": "best[height<=480]",
            #     "720P": "best[height<=720]",
            #     "1080P": "best[height<=1080]",
            # }
            # markup, temp_row = [], []
            # for quality, data in available_options.items():
            #     temp_row.append(types.InlineKeyboardButton(quality, callback_data=data))
            #     if len(temp_row) == 3:  # Add a row every 3 buttons
            #         markup.append(temp_row)
            #         temp_row = []
            # # Add any remaining buttons as the last row
            # if temp_row:
            #     markup.append(temp_row)
            # self._bot_msg.edit_text("Choose the format", reply_markup=types.InlineKeyboardMarkup(markup))
            # return None

        formats.extend(maps[f"{quality}-{format_}"])
        # extend default formats if not high*
        if quality != "high":
            formats.extend(defaults)
        return formats

    def _download(self, formats) -> list:
        output = Path(self._tempdir.name, "%(title).70s.%(ext)s").as_posix()
        
        # Try to get proxy for YouTube downloads
        proxy = None
        used_proxies = set()
        max_retries = 10
        
        if is_youtube(self._url):
            try:
                proxy = get_proxy(PROXY_FILE)
            except (FileNotFoundError, Exception) as e:
                logging.warning(f"Could not load proxy: {e}")
        
        retries = 0
        while retries < max_retries:
            ydl_opts = {
                "progress_hooks": [lambda d: self.download_hook(d)],
                "outtmpl": output,
                "restrictfilenames": False,
                "quiet": True,
                "match_filter": match_filter,
                "concurrent_fragments": 16,
                "buffersize": 4194304,
                "retries": 6,
                "fragment_retries": 6,
                "skip_unavailable_fragments": True,
                "embed_metadata": True,
                "embed_thumbnail": True,
                "writethumbnail": False,
            }
            
            # setup cookies for youtube only
            if is_youtube(self._url):
                # use cookies from browser firstly
                if browsers := os.getenv("BROWSERS"):
                    ydl_opts["cookiesfrombrowser"] = browsers.split(",")
                if os.path.isfile("youtube-cookies.txt") and os.path.getsize("youtube-cookies.txt") > 100:
                    ydl_opts["cookiefile"] = "youtube-cookies.txt"
                # try add extract_args if present
                if potoken := os.getenv("POTOKEN"):
                    ydl_opts["extractor_args"] = {"youtube": ["player-client=web,default", f"po_token=web+{potoken}"]}
                    # for new version? https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
                    # ydl_opts["extractor_args"] = {
                    #     "youtube": [f"po_token=web.player+{potoken}", f"po_token=web.gvs+{potoken}"]
                    # }
                
                # Configure JavaScript runtime (deno) if not already set
                if "js_runtimes" not in ydl_opts:
                    deno_path = shutil.which("deno")
                    if deno_path:
                        ydl_opts["js_runtimes"] = {"deno": {"path": deno_path}}
                    else:
                        # Fallback: just use 'deno' and let yt-dlp find it
                        ydl_opts["js_runtimes"] = {"deno": {}}
                
                # Enable remote components for JavaScript challenge solving (recommended)
                if "remote_components" not in ydl_opts:
                    ydl_opts["remote_components"] = ["ejs:github"]
                
                # Add proxy if available
                if proxy:
                    try:
                        proxy_str = construct_proxy_string(proxy)
                        ydl_opts["proxy"] = f"http://{proxy_str}"
                        logging.info(f"Using proxy from {proxy.get('city', 'Unknown')}, {proxy.get('country', 'Unknown')}")
                    except Exception as e:
                        logging.warning(f"Could not construct proxy string: {e}")

            if self._url.startswith("https://drive.google.com"):
                # Always use the `source` format for Google Drive URLs.
                formats = ["source"] + formats

            files = None
            for f in formats:
                ydl_opts["format"] = f
                logging.info("yt-dlp options: %s", ydl_opts)
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([self._url])
                    files = list(Path(self._tempdir.name).glob("*"))
                    break
                except (yt_dlp.utils.DownloadError, Exception) as e:
                    error_msg = str(e).lower()
                    # Check for proxy-related errors that should trigger retry with new proxy
                    if is_youtube(self._url) and proxy and ("403" in error_msg or "forbidden" in error_msg or "sign in to" in error_msg):
                        logging.warning(f"Got error with proxy: {error_msg[:100]}")
                        # Try to get a new proxy
                        try:
                            proxies = load_proxies(PROXY_FILE)
                            available_proxies = [
                                p for p in proxies
                                if f"{p.get('host')}:{p.get('port')}" not in used_proxies
                            ]
                            if not available_proxies:
                                available_proxies = proxies
                                used_proxies.clear()
                            if available_proxies:
                                proxy = random.choice(available_proxies)
                                used_proxies.add(f"{proxy.get('host')}:{proxy.get('port')}")
                                retries += 1
                                continue
                        except Exception as proxy_error:
                            logging.error(f"Error getting new proxy: {proxy_error}")
                            # If we can't get a new proxy, try updating the proxy list
                            try:
                                update_proxies(filename=PROXY_FILE, verbose=False)
                                proxy = get_proxy(PROXY_FILE)
                                retries += 1
                                continue
                            except Exception:
                                pass
                    # If it's the last format or not a proxy error, re-raise
                    if f == formats[-1] or not is_youtube(self._url) or not proxy:
                        raise
                    # Otherwise, try next format
                    continue

            if files:
                return files
            
            # If we got here, all formats failed
            break

        return files if files else []

    def _start(self, formats=None):
        # start download and upload, no cache hit
        # user can choose format by clicking on the button(custom config)
        default_formats = self._setup_formats()
        if formats is not None:
            # formats according to user choice
            default_formats = formats + self._setup_formats()
        self._download(default_formats)
        self._upload()
