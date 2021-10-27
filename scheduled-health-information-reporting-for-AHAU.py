import difflib
import logging
import os
from pathlib import Path
from random import random
from threading import Thread
from time import sleep

import yaml
from apscheduler.schedulers.background import BlockingScheduler
from lxml.etree import HTML
from selenium.webdriver.common.by import By

import glb

region_code = ['340000', '340100', '340104']
region_name = ['安徽省', '合肥市', '蜀山区']

logging.basicConfig(format='%(asctime)s %(message)s')
config_path = Path('config.private.yaml')
config = yaml.safe_load(config_path.read_text())

parser = glb.parser
parser.add_argument('-i', action='store_true', help='立即执行')
parser.add_argument('--driver', default='chrome', choices=['chrome', 'firefox'], help='Web Driver')
cli_args = parser.parse_args()
run_immediately = cli_args.i
web_driver = cli_args.driver
glb.request_limits['pushplus.plus'] = glb.Limit(glb.SleepTime(20))
script_source = Path('previous.txt').read_text().strip().splitlines()


def login(driver, account_id, password):
    def func():
        driver.get('http://fresh.ahau.edu.cn/yxxt-v5/web/jkxxtb/tbJkxx.zf')
        sleep(5)
        driver.find_element(By.ID, 'zh').send_keys(account_id)
        driver.find_element(By.ID, 'mm').send_keys(password)
        driver.find_element(By.ID, 'dlan').click()
        sleep(5)
        driver.switch_to.alert.accept()
        if driver.current_url != 'http://fresh.ahau.edu.cn/yxxt-v5/web/jkxxtb/tbJkxx.zf':
            logging.warning(f'login failed: {account_id} <<<{driver.page_source=}>>>')
            notify('login failed', f'{account_id}')
            driver.close()
            return False
        sleep(5)
        return True

    return glb.run_func_catch(func, catch_func=catch_func)


def submit(account):
    def func():
        if not run_immediately:
            sleep(random() * 60 * 30)
        account_id = account['account-id']
        password = account['password']

        driver = get_web_driver()
        if not login(driver, account_id, password):
            return
        html = HTML(driver.page_source)
        source = get_script_source(driver, html)
        if diff := '\n'.join(tuple(difflib.unified_diff(
                script_source, source, fromfile='previous', tofile='current', lineterm=''
        ))):
            logging.warning('===\n{}'.format(diff))
            notify(f'page changed', f'```diff\n{diff}\n```')
            driver.close()
            os._exit(1)

        name = html.xpath("//input[@id='xm']/@value")[0]
        driver.execute_script(f'''
            $('#dqszdmc').val('{''.join(region_name)}');
            $('#dqszddm').val('{region_code[-1]}');
        ''')
        sleep(5)

        driver.find_element(By.XPATH, "//button[text()='提交']").click()
        sleep(5)
        if driver.find_elements(By.XPATH, "//div[text()='保存数据成功']"):
            logging.warning(f'success: {account_id} {name}')
        else:
            logging.warning(f'submit failed: {account_id} {name} <<<{driver.page_source=}>>>')
            notify('submit failed', f'{account_id} {name}')
        driver.close()

    return glb.run_func_catch(func, catch_func=catch_func)


def run(wait=False):
    threads = []
    for account in config['accounts']:
        thread = Thread(target=submit, args=(account,))
        if wait:
            threads.append(thread)
        thread.start()
    for t in threads:
        t.join()


def get_web_driver():
    if web_driver == 'chrome':
        from selenium.webdriver.chrome.webdriver import WebDriver
        from selenium.webdriver.chrome.options import Options
    else:
        from selenium.webdriver.firefox.webdriver import WebDriver
        from selenium.webdriver.firefox.options import Options
    options = Options()
    options.add_argument("--headless")
    return WebDriver(options=options)


def get_script_source(driver, html=None):
    html = HTML(driver.page_source) if html is None else html
    return html.xpath('//script[not(@src)]/text()')[0].strip().splitlines()


def check_page_func():
    driver = get_web_driver()
    while not login(driver, *config['accounts'][0].values()):
        sleep(60 * 10)
    source = get_script_source(driver)
    driver.close()
    return source


def check_page():
    sleep(60 * 10)
    sleep_time = glb.SleepTimeRange(
        {(0, 6): glb.SleepTime(60 * 60 * 6), (22, 24): glb.SleepTime(60 * 60 * 8)}, glb.SleepTime(60 * 10)
    )
    for diff in glb.monitor_diff(check_page_func, sleep_time, script_source):
        if diff:
            diff = '\n'.join(diff)
            logging.warning('===\n{}'.format(diff))
            notify(f'page changed', f'```diff\n{diff}\n```')
            os._exit(1)


def catch_func(e, k):
    notify('error', f'```\n{e}\n```')
    return True


def notify(title, content):
    glb.client.send_request(
        'post', 'https://www.pushplus.plus/send', json={
            'token': config['notification']['token'],
            'title': f'health information reporting: {title}',
            'content': str(content),
            'template': 'markdown',
        }
    )


def main():
    Thread(target=check_page).start()
    if run_immediately:
        run(wait=True)
        logging.warning('immediately running finished')
    scheduler = BlockingScheduler(job_defaults={'misfire_grace_time': 3600, 'coalesce': True})
    scheduler.add_job(run, 'cron', hour=7)
    scheduler.add_job(run, 'cron', hour=12)
    scheduler.add_job(run, 'cron', hour=19, minute=30)
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logging.warning('EXITING')
        os._exit(0)


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

main()
