# ==============================================================================
# Copyright (C) 2021 Evil0ctal
#
# This file is part of the Douyin_TikTok_Download_API project.
#
# This project is licensed under the Apache License 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

import asyncio
import sys
import re
import json
import uuid
import httpx
import time
from urllib.parse import urlparse, parse_qs
from loguru import logger
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.append(str(Path(__file__).resolve().parents[2]))

from crawlers.douyin.web.web_crawler import DouyinWebCrawler
from crawlers.tiktok.web.web_crawler import TikTokWebCrawler
from crawlers.bilibili.web.web_crawler import BilibiliWebCrawler


class HybridCrawler:
    """混合爬虫类，统一处理多个平台的视频解析"""

    def __init__(self):
        # 初始化各平台爬虫
        self.douyin_crawler = DouyinWebCrawler()
        self.tiktok_crawler = TikTokWebCrawler()
        self.bilibili_crawler = BilibiliWebCrawler()
        
        # 平台URL模式匹配
        self.platform_patterns = {
            'douyin': re.compile(r'(?:douyin\.com|ies\.douyin\.com|v\.douyin\.com)'),
            'tiktok': re.compile(r'(?:tiktok\.com|vt\.tiktok\.com|www\.tiktok\.com)'),
            'bilibili': re.compile(r'(?:bilibili\.com|b23\.tv|www\.bilibili\.com)')
        }

    async def identify_platform(self, url: str) -> str:
        """根据URL识别平台"""
        for platform, pattern in self.platform_patterns.items():
            if pattern.search(url):
                return platform
        return 'unknown'

    async def hybrid_parsing_single_video(self, url: str, minimal: bool = False):
        """统一视频解析入口"""
        platform = await self.identify_platform(url)
        
        if platform == 'douyin':
            result = await self.douyin_crawler.parsing_single_video(url, minimal)
        elif platform == 'tiktok':
            result = await self.tiktok_crawler.parsing_single_video(url, minimal)
        elif platform == 'bilibili':
            result = await self.bilibili_crawler.parsing_single_video(url, minimal)
        else:
            return {'error': 'Unsupported platform'}
        
        return result


# 测试代码
if __name__ == '__main__':
    import asyncio
    
    async def test():
        crawler = HybridCrawler()
        
        # 测试抖音
        douyin_url = "https://v.douyin.com/DO5Na3M96Ac/"
        result = await crawler.hybrid_parsing_single_video(douyin_url, minimal=True)
        print("抖音测试结果:", json.dumps(result, ensure_ascii=False, indent=2))
    
    asyncio.run(test())
