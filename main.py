import asyncio
import contextlib
import logging
import os
import signal
import time
from asyncio import create_task, sleep
from asyncio.exceptions import CancelledError
from pathlib import Path
from random import random

import playwright
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from lxml.etree import HTML
from playwright.async_api import async_playwright

from util import CLIENT, LOG_LEVEL, Limit, PARSER, REQUEST_LIMITS, SleepTime, SleepTimeRange, async_monitor_diff, \
    async_run_func_catch, get_diff, run_main_coroutine

config_dir_path = Path('config')
config_path = config_dir_path / 'config.private.yaml'
config = yaml.safe_load(config_path.read_text())

parser = PARSER
parser.add_argument('-i', action='store_true', help='立即执行')
cli_args = parser.parse_args()
run_immediately = cli_args.i
script_source = (config_dir_path / 'previous.txt').read_text().strip().splitlines()
tasks = set()
shutdown_variables = {'killed': False}
browser: playwright.async_api._generated.Browser = None


async def login(page, account_id, password, timeout=60 * 60 * 3):
    async def func():
        start = time.time()
        while True:
            if time.time() - start > timeout:
                logging.warning(f'Login failed: {account_id} <<<{page.page_source=}>>>')
                await notify('Login failed', f'{account_id}')
                return False
            try:
                await page.goto('http://fresh.ahau.edu.cn/yxxt-v5/web/jkxxtb/tbJkxx.zf')
            except playwright._impl._api_types.Error as e:
                logging.exception(e)
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
            if not run_immediately:
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
            if diff := '\n'.join(get_diff(script_source, source)):
                logging.warning('Page changed:\n{}'.format(diff))
                await notify(f'Page changed', f'```diff\n{diff}\n```')
                create_task(shutdown())
                return

            name = html.xpath("//input[@id='xm']/@value")[0]
            await page.evaluate(f'''
                $('#dqszdmc').val('{''.join(region_name)}');
                $('#dqszddm').val('{region_code[-1]}');
            ''')
            await sleep(5)

            async with page.expect_response('**/tbBcJkxx.zf') as response:
                await page.click("//button[text()='提交']")
                await sleep(5)
            response = await (await response.value).json()
            if response['status'] == 'success':
                await page.wait_for_selector("//div[text()='保存数据成功']", state='attached')
                logging.warning(f'Success: {account_id} {name}')
            else:
                logging.warning(f'Submit failed: {account_id} {name} <<<{source=}>>>')
                await notify('Submit failed', f'{account_id} {name}')

    return await async_run_func_catch(func, catch_func=catch_func)


async def check_page():
    async def func():
        async with contextlib.AsyncExitStack() as stack:
            context, page = await new_context()
            stack.push_async_callback(context.close)
            while not await login(page, *config['accounts'][0].values()):
                await sleep(60 * 10)
            source = await get_script_source(page=page)
            return source

    await sleep(60 * 10)
    sleep_time = SleepTimeRange(
        {(0, 6): SleepTime(60 * 60 * 6), (22, 24): SleepTime(60 * 60 * 8)}, SleepTime(60 * 10)
    )
    async for diff in async_monitor_diff(func, sleep_time, script_source):
        if diff:
            diff = '\n'.join(diff)
            logging.warning('Page changed:\n{}'.format(diff))
            await notify(f'Page changed', f'```diff\n{diff}\n```')
            create_task(shutdown())
            return


async def new_context():
    context = await browser.new_context()
    return context, await context.new_page()


async def get_script_source(page=None, html=None):
    if page:
        html = HTML(await page.content())
    return html.xpath('//script[not(@src)]/text()')[0].strip().splitlines()


async def catch_func(e, local):
    if isinstance(e, CancelledError):
        return False, False
    await notify('Error', f'```\n{e}\n```')
    return True, True


async def notify(title, content):
    if getattr(logging, LOG_LEVEL) > logging.DEBUG:
        await CLIENT.send_request(
            'post', 'https://www.pushplus.plus/send', json={
                'token': config['notification']['token'],
                'title': f'Health Information Reporting: {title}',
                'content': str(content),
                'template': 'markdown',
            }
        )


async def shutdown():
    if shutdown_variables['killed']:
        os._exit(1)
    shutdown_variables['killed'] = True
    logging.warning('Exiting')
    for t in tasks:
        t.cancel()
    await asyncio.wait(tasks)
    logging.debug(f'{tasks=}')
    shutdown_variables['event'].set()


async def run(return_cancelled_error=False):
    async def func():
        await asyncio.gather(*(submit(a) for a in config['accounts']), return_exceptions=True)

    async def catch(e, local):
        await notify('Error', f'```\n{e}\n```')
        return True, True

    catch_function = catch if return_cancelled_error else catch_func
    await async_run_func_catch(func, catch_func=catch_function)


async def main():
    global browser
    logging.basicConfig(format='%(asctime)s %(message)s')
    REQUEST_LIMITS['pushplus.plus'] = Limit(SleepTime(20))

    async with contextlib.AsyncExitStack() as stack:
        play = await stack.enter_async_context(async_playwright())
        browser = await play.chromium.launch()
        stack.push_async_callback(play.stop)
        stack.push_async_callback(browser.close)
        scheduler = AsyncIOScheduler(job_defaults={'misfire_grace_time': 3600, 'coalesce': True})
        loop = asyncio.get_running_loop()
        for s in (signal.SIGINT, signal.SIGTERM, signal.SIGQUIT):
            loop.add_signal_handler(s, lambda: create_task(shutdown()))
        event = asyncio.Event()
        shutdown_variables['event'] = event

        tasks.add(create_task(async_run_func_catch(check_page, catch_func=catch_func)))
        if run_immediately:
            try:
                task = create_task(run(return_cancelled_error=True))
                tasks.add(task)
                await task
                tasks.discard(task)
                logging.warning('immediately running finished')
            except CancelledError:
                return
        scheduler.add_job(run, 'cron', hour=7)
        scheduler.add_job(run, 'cron', hour=12)
        scheduler.add_job(run, 'cron', hour=19, minute=30)
        scheduler.start()
        stack.callback(scheduler.shutdown)
        stack.push_async_callback(event.wait)


region_code = ['340000', '340100', '340104']
region_name = ['安徽省', '合肥市', '蜀山区']

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
