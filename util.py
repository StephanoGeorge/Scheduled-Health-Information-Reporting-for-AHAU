import argparse
import asyncio
import difflib
import logging
import random
import re
import time
from asyncio import Lock, create_task, sleep
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from http.cookiejar import CookiePolicy
from typing import Union

import coloredlogs
import httpx
from lxml.etree import HTML


@dataclass
class SleepTime:
    time: float = 0
    range: tuple[float, float] = None

    def get(self):
        if self.range is not None:
            return random.uniform(*self.range)
        else:
            return self.time


@dataclass
class SleepTimeRange:
    data: dict[tuple[float, float], SleepTime]
    default: SleepTime

    def __getitem__(self, item):
        for k, v in self.data.items():
            s, e = k
            if s <= item <= e:
                return v.get()
        return self.default.get()


@dataclass
class Limit:
    sleep_time: SleepTime = field(default_factory=SleepTime)

    def __post_init__(self):
        self.lock = Lock()

    async def trigger(self):
        async def func():
            await sleep(self.sleep_time.get())
            self.lock.release()

        await self.lock.acquire()
        create_task(func())


class ResponseEnhance:
    def __init__(self, response):
        self.response: httpx.Response = response

    @property
    def tree(self):
        return HTML(self.response.text)

    def __getattribute__(self, item):
        try:
            return super().__getattribute__(item)
        except AttributeError:
            return getattr(self.response, item)


# 网络请求工具类
class Client(httpx.AsyncClient):
    def __init__(self, accept_cookies=True, timeout=5, **kwargs):
        super().__init__(headers=REQUEST_HEADERS, http2=True, timeout=timeout, **kwargs)
        # super().__init__()
        # self.headers.update(REQUEST_HEADERS)
        if not accept_cookies:
            self.cookies.jar.set_policy(BlockAll())
            # self.cookies.set_policy(BlockAll())
        self.timeout = timeout

    # 发送请求
    async def send_request(
            self, method, url,
            before_func=lambda *a: None, check_func=lambda *a: False, catch_func=lambda *a: True, **kwargs
    ):
        kwargs.setdefault('timeout', self.timeout)
        headers = kwargs.setdefault('headers', {})
        headers['Host'] = re.search(r'^https?://(.+?)(/|$)', url).group(1)
        host, limit_key = headers['Host'], headers['Host']
        host_count = host.count('.')
        limit = None
        for i in range(host_count):
            if i == host_count - 1 or host in REQUEST_LIMITS:
                limit = REQUEST_LIMITS[host]
                REQUEST_LIMITS[headers['Host']] = limit
                break
            host = host[host.find('.') + 1:]
        while True:
            try:
                before_func(method, kwargs)
                logging.debug('limit.trigger')
                await limit.trigger()
                response: httpx.Response = await getattr(self, method)(url, **kwargs)
                if check_func(response, locals()):
                    # logging.warning(f"retry: {response.status_code} {url} {kwargs}")
                    continue
                logging.debug(f"{response.status_code} {url} {kwargs}")
                return ResponseEnhance(response)
            except Exception as e:
                es = (
                    httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.ReadTimeout,
                    # requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError,
                    # requests.exceptions.ReadTimeout, requests.exceptions.ChunkedEncodingError,
                    # requests.exceptions.SSLError
                )
                if catch_func(e, locals()) or type(e) not in es:
                    # 进一步捕捉
                    logging.exception(f'Exception: {type(e)}, {e}')


class BlockAll(CookiePolicy):
    return_ok = set_ok = domain_return_ok = path_return_ok = lambda self, *args, **kwargs: False
    netscape = True
    rfc2965 = hide_cookie2 = False


class FIFOExitStack:
    def __init__(self):
        self.stack = []

    def __enter__(self):
        return self.stack

    def __exit__(self, exc_type, exc_val, exc_tb):
        for callback in self.stack:
            callback()


class AsyncFIFOExitStack:
    def __init__(self):
        self.stack = []

    async def __aenter__(self):
        return self.stack

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        for callback in self.stack:
            await callback()


def monitor_diff(func, sleep_time, previous=None):
    previous = [] if not previous else previous
    while True:
        current = func()
        diff = get_diff(previous, current)
        yield diff
        previous = current
        time.sleep(sleep_time[datetime.now().hour])


async def async_monitor_diff(func, sleep_time, previous=None):
    previous = [] if not previous else previous
    while True:
        current = await func()
        diff = get_diff(previous, current)
        yield diff
        previous = current
        await sleep(sleep_time[datetime.now().hour])


def get_diff(previous, current):
    return tuple(difflib.unified_diff(previous, current, fromfile='previous', tofile='current', lineterm=''))


def run_func_catch(func, catch_func=None):
    if not catch_func:
        def catch_func(*a):
            return True, True
    while True:
        try:
            return func()
        except Exception as e:
            retry, catch = catch_func(e, locals())
            if catch:
                logging.exception(e)
            if not retry:
                return e


async def async_run_func_catch(func, catch_func=None):
    if not catch_func:
        async def catch_func(*a):
            return True, True
    while True:
        try:
            return await func()
        except Exception as e:
            retry, catch = await catch_func(e, locals())
            if catch:
                logging.exception(e)
            if not retry:
                return e


REQUEST_HEADERS = {
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
CLIENT: Union[Client, None] = None


def run_main_coroutine(main):
    async def func():
        global CLIENT
        CLIENT = Client()
        result = await main
        await CLIENT.aclose()
        return result

    # 关闭不重要的日志
    logging.getLogger('urllib3').setLevel(logging.FATAL)
    logging.getLogger('hpack').setLevel(logging.INFO)
    return asyncio.run(func())


PARSER = argparse.ArgumentParser()
PARSER.add_argument('-l', default='info', help='log level')
_arguments = PARSER.parse_known_args()[0]
LOG_LEVEL = logging.getLevelName(_arguments.l.upper())
# 启用彩色日志
coloredlogs.install(fmt='%(asctime)s %(levelname)s %(message)s', level=LOG_LEVEL)
REQUEST_LIMITS = defaultdict(Limit)
