import asyncio
import contextlib
import os
import signal
import time
from asyncio import create_task, sleep
from asyncio.exceptions import CancelledError
from pathlib import Path
from random import random

import playwright
import tzlocal
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from lxml.etree import HTML
from playwright.async_api import async_playwright

from functions import page_js_code
from util import CLIENT, LOGGER, Limit, PARSER, REQUEST_LIMITS, SleepTime, SleepTimeRange, \
    async_monitor_diff, \
    async_run_func_catch, get_diff, run_main_coroutine

CONFIG_DIR_PATH = Path('config')
CONFIG_PATH = CONFIG_DIR_PATH / 'config.private.yaml'
CONFIG = yaml.safe_load(CONFIG_PATH.read_text())

PARSER.add_argument('-i', action='store_true', help='立即执行')
CLI_ARGS = PARSER.parse_args()
RUN_IMMEDIATELY = CLI_ARGS.i
PREVIOUS_PATH = CONFIG_DIR_PATH / 'previous.txt'
PREVIOUS_PATH.touch()
SCRIPT_SOURCE = PREVIOUS_PATH.read_text().strip().splitlines()
TASKS = set()
SHUTDOWN_VARIABLES = {'killed': False}
# noinspection PyProtectedMember
BROWSER: playwright.async_api._generated.Browser = None


async def login(page, account_id, password, timeout=60 * 60 * 3):
    async def func():
        start = time.time()
        while True:
            if time.time() - start > timeout:
                LOGGER.warning(f'Login failed: {account_id} <<<{page.page_source=}>>>')
                await notify('Login failed', f'{account_id}')
                return False
            try:
                await page.goto('http://fresh.ahau.edu.cn/yxxt-v5/web/jkxxtb/tbJkxx.zf')
            except playwright._impl._api_types.Error as e:
                LOGGER.exception(e)
                continue
            await sleep(5)
            await page.fill('#zh', account_id)
            await page.fill('#mm', password)
            await sleep(5)
            await page.click('#dlan')
            await sleep(5)
            if page.url != 'http://fresh.ahau.edu.cn/yxxt-v5/web/jkxxtb/tbJkxx.zf':
                await sleep(60 * 10)
                continue
            await sleep(5)
            return True

    return await async_run_func_catch(func, catch_func=catch_func)


async def submit(account):
    async def func():
        async with contextlib.AsyncExitStack() as stack:
            if not RUN_IMMEDIATELY:
                await sleep(random() * 30 * 60)
            account_id = account['account-id']
            password = account['password']
            context, page = await new_context()
            stack.push_async_callback(context.close)
            stack.push_async_callback(page.close)
            logged = await login(page, account_id, password)
            if not logged:
                return
            html = HTML(await page.content())
            source = await get_script_source(html=html)
            if SCRIPT_SOURCE:
                if diff := '\n'.join(get_diff(SCRIPT_SOURCE, source.splitlines())):
                    await handle_page_changing(diff, source)
                    return

            name = html.xpath("//input[@id='xm']/@value")[0]
            await page.evaluate(page_js_code())
            await sleep(5)

            async with page.expect_response('**/tbBcJkxx.zf') as response:
                await page.click("//button[text()='提交']")
                await sleep(5)
            response = await (await response.value).json()
            if response['status'] == 'success':
                await page.wait_for_selector("//div[text()='保存数据成功']", state='attached')
                LOGGER.warning(f'Success: {account_id} {name}')
            else:
                LOGGER.warning(f'Submit failed: {account_id} {name} <<<{source=}>>>')
                await notify('Submit failed', f'{account_id} {name}')

    return await async_run_func_catch(func, catch_func=catch_func)


async def check_page():
    async def fetch_script_source():
        async with contextlib.AsyncExitStack() as stack:
            context, page = await new_context()
            stack.push_async_callback(context.close)
            while not await login(page, *CONFIG['accounts'][0].values()):
                ...
            return await get_script_source(page=page)

    async def fetch_script_source_lines():
        return (await fetch_script_source()).splitlines()

    global SCRIPT_SOURCE
    if not SCRIPT_SOURCE:
        SCRIPT_SOURCE = await fetch_script_source()
        PREVIOUS_PATH.write_text(SCRIPT_SOURCE)
    await sleep(60 * 10)
    sleep_time = SleepTimeRange(
        {(0, 6): SleepTime(60 * 60 * 6), (22, 24): SleepTime(60 * 60 * 8)}, SleepTime(60 * 10)
    )
    async for diff, current in async_monitor_diff(fetch_script_source_lines, sleep_time, SCRIPT_SOURCE):
        if diff:
            diff = '\n'.join(diff)
            await handle_page_changing(diff, current)
            return


async def handle_page_changing(diff, current):
    LOGGER.warning('Page changed:\n{}'.format(diff))
    PREVIOUS_PATH.write_text(current)
    await notify(f'Page changed', f'```diff\n{diff}\n```')
    create_task(shutdown())


async def get_script_source(page=None, html=None) -> str:
    if page:
        html = HTML(await page.content())
    return html.xpath('//script[not(@src)]/text()')[0].strip()


async def new_context():
    context = await BROWSER.new_context()
    return context, await context.new_page()


async def catch_func(e, local):
    if isinstance(e, CancelledError):
        return False, True
    LOGGER.exception(e)
    await notify('Error', f'```\n{e}\n```')
    return True, False


async def notify(title, content):
    await CLIENT.send_request(
        'post', 'https://www.pushplus.plus/send', json={
            'token': CONFIG['notification']['token'],
            'title': f'Health Information Reporting: {title}',
            'content': str(content),
            'template': 'markdown',
        }
    )


async def shutdown():
    if SHUTDOWN_VARIABLES['killed']:
        os._exit(1)
    SHUTDOWN_VARIABLES['killed'] = True
    LOGGER.warning('Exiting')
    for t in TASKS:
        t.cancel()
    if TASKS:
        await asyncio.wait(TASKS)
    LOGGER.debug(f'{TASKS=}')
    SHUTDOWN_VARIABLES['event'].set()


async def run(return_cancelled_error=False):
    async def func():
        await asyncio.gather(*(submit(a) for a in CONFIG['accounts']), return_exceptions=True)

    async def catch(e, local):
        LOGGER.exception(e)
        await notify('Error', f'```\n{e}\n```')
        return True, False

    catch_function = catch if return_cancelled_error else catch_func
    await async_run_func_catch(func, catch_func=catch_function)


async def main():
    global BROWSER
    REQUEST_LIMITS['pushplus.plus'] = Limit(SleepTime(20))

    async with contextlib.AsyncExitStack() as stack:
        play = await stack.enter_async_context(async_playwright())
        BROWSER = await play.chromium.launch()
        stack.push_async_callback(play.stop)
        stack.push_async_callback(BROWSER.close)
        scheduler = AsyncIOScheduler(
            job_defaults={'misfire_grace_time': 3600, 'coalesce': True}, timezone=str(tzlocal.get_localzone())
        )
        loop = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGQUIT):
            loop.add_signal_handler(s, lambda: create_task(shutdown()))
        event = asyncio.Event()
        SHUTDOWN_VARIABLES['event'] = event

        # TASKS.add(create_task(async_run_func_catch(check_page, catch_func=catch_func)))
        if RUN_IMMEDIATELY:
            try:
                task = create_task(run(return_cancelled_error=True))
                TASKS.add(task)
                await task
                TASKS.discard(task)
                LOGGER.warning('immediately running finished')
            except CancelledError:
                return
        scheduler.add_job(run, 'cron', hour=7)
        scheduler.add_job(run, 'cron', hour=12)
        scheduler.add_job(run, 'cron', hour=19, minute=30)
        scheduler.start()
        stack.callback(scheduler.shutdown)
        stack.push_async_callback(event.wait)


headers = {
    'Host': 'fresh.ahau.edu.cn',
    'Origin': 'http://fresh.ahau.edu.cn',
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:77.0) Gecko/20100101 Firefox/77.0',
    'Accept': '*/*; q=0.01',
    'Accept-Language': 'zh-CN,zh-TW;q=0.8,zh-HK;q=0.7,zh;q=0.5,en-US;q=0.3,en;q=0.2',
    'Accept-Encoding': 'gzip, deflate',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'X-Requested-With': 'XMLHttpRequest',
}

run_main_coroutine(main())
