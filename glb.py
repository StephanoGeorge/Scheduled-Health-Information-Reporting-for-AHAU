import argparse
import logging
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from http.cookiejar import CookiePolicy
from threading import Lock, Thread
from time import sleep

import chardet
import coloredlogs
# import httpx
import requests
from lxml.etree import HTML
from requests import Response


@dataclass
class SleepTime:
    time: float = 0
    range: list[float, float] = None


@dataclass
class Limit:
    sleep_time: SleepTime = field(default_factory=SleepTime)

    def __post_init__(self):
        self.lock = Lock()

    def trigger(self):
        def func():
            if self.sleep_time.range is not None:
                sleep(random.uniform(*self.sleep_time.range))
            else:
                sleep(self.sleep_time.time)
            self.lock.release()

        self.lock.acquire()
        Thread(target=func).start()


class ResponseEnhance:
    def __init__(self, response):
        self.response: Response = response

    @property
    def tree(self):
        return HTML(self.response.text)

    def __getattribute__(self, item):
        try:
            return super().__getattribute__(item)
        except AttributeError:
            return getattr(self.response, item)


# 网络请求类
class Client(requests.Session):
    def __init__(self, random_ua=False, accept_cookies=True, timeout=5, **kwargs):
        # super().__init__(headers=request_headers, http2=True, timeout=6, **kwargs)
        super().__init__()
        self.headers.update(request_headers)
        self.random_ua = random_ua
        if not accept_cookies:
            # self.cookies.jar.set_policy(BlockAll())
            self.cookies.set_policy(BlockAll())
        self.timeout = timeout

    # 发送请求
    def send_request(self, method, url, before_func=None, check_func=None, decode=False, catch_exception=None,
                     **kwargs):
        kwargs.setdefault('timeout', self.timeout)
        headers = kwargs.setdefault('headers', {})
        headers['Host'] = re.search(r'^https?://(.+?)(/|$)', url).group(1)
        host, limit_key = headers['Host'], headers['Host']
        host_count = host.count('.')
        limit = None
        proxy = None
        for i in range(host_count):
            if i == host_count - 1 or host in request_limits:
                limit = request_limits[host]
                request_limits[headers['Host']] = limit
                break
            host = host[host.find('.') + 1:]
        while True:
            try:
                if self.random_ua:
                    from . import ua  # 初始化需要解压文件
                    headers['User-Agent'] = ua.ua_rotator.get_random_user_agent()
                if before_func:
                    before_func(method, kwargs)
                logging.debug('limit.trigger')
                limit.trigger()
                response: Response = getattr(self, method)(url, **kwargs)
                if check_func:
                    if check_func(response, locals()):
                        # logging.warning(f"retry: {response.status_code} {url} {kwargs}")
                        continue
                logging.debug(f"{response.status_code} {url} {kwargs}")
                if decode:
                    response.encoding = chardet.detect(response.content)['encoding']
                return ResponseEnhance(response)
            except Exception as e:
                es = (
                    # httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.ReadTimeout,
                    requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError,
                    requests.exceptions.ReadTimeout, requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.SSLError
                )
                if not catch_exception or not catch_exception(e, locals()) or type(e) not in es:
                    # 进一步捕捉
                    logging.error(f'Exception: {type(e)}, {e}', exc_info=True)


class BlockAll(CookiePolicy):
    return_ok = set_ok = domain_return_ok = path_return_ok = lambda self, *args, **kwargs: False
    netscape = True
    rfc2965 = hide_cookie2 = False


request_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/77.0.3835.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    # 'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Language': 'zh-CN,zh-TW;q=0.8,zh-HK;q=0.7,zh;q=0.5,en-US;q=0.3,en;q=0.2',
    'Accept-Encoding': 'gzip, deflate',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'TE': 'Trailers',
    'Pragma': 'no-cache',
    'Cache-Control': 'no-cache',
}

parser = argparse.ArgumentParser()
parser.add_argument('-l', default='info', help='log level')
arguments = parser.parse_known_args()[0]
# 启用彩色日志
coloredlogs.install(fmt='%(asctime)s %(levelname)s %(message)s', level=getattr(logging, arguments.l.upper()))
# 关闭不重要的日志
logging.getLogger('urllib3').setLevel(logging.FATAL)
logging.getLogger('chardet').setLevel(logging.INFO)
logging.getLogger('hpack').setLevel(logging.INFO)
logging.getLogger('peewee').setLevel(logging.INFO)

request_limits = defaultdict(Limit)
client = Client()
