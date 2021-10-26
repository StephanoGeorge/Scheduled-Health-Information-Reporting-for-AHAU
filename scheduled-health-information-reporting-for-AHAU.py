import logging
from base64 import b64decode
from pathlib import Path
from random import random
from threading import Thread
from time import sleep

import esprima
import yaml
from apscheduler.schedulers.background import BlockingScheduler
from lxml.etree import HTML
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.webdriver import WebDriver

import glb

region_code = ['340000', '340100', '340104']
region_name = ['安徽省', '合肥市', '蜀山区']

logging.basicConfig(format='%(asctime)s %(message)s')
config_path = Path('config.private.yaml')
config = yaml.safe_load(config_path.read_text())

parser = glb.parser
parser.add_argument('-i', action='store_true', help='立即执行')
cli_args = parser.parse_args()
run_immediately = cli_args.i
glb.request_limits['pushplus.plus'] = glb.Limit(glb.SleepTime(time=20))
accept_page = True
page_pattern = {
    'location': esprima.tokenize('''$('.get_address').on('click', function() {
            $('#dqszdmc').val(province + city + district);
            $('#dqszddm').val(adcode);
        })''')
}


def submit(account, check_page):
    global accept_page
    if not run_immediately:
        sleep(random() * 60 * 30)
    account_id = account['account-id']
    password = account['password']

    options = Options()
    options.add_argument("--headless")
    driver = WebDriver(options=options)

    driver.get('http://fresh.ahau.edu.cn/yxxt-v5/web/jkxxtb/tbJkxx.zf')
    sleep(5)
    driver.find_element(By.ID, 'zh').send_keys(account_id)
    driver.find_element(By.ID, 'mm').send_keys(password)
    driver.find_element(By.ID, 'dlan').click()
    sleep(5)
    driver.switch_to.alert.accept()
    if driver.current_url != 'http://fresh.ahau.edu.cn/yxxt-v5/web/jkxxtb/tbJkxx.zf':
        logging.warning(f'login failed: {account["account-id"]} <<<{driver.page_source=}>>>')
        notify('login failed', f'{account["account-id"]}')
        driver.close()
        return
    sleep(5)

    if check_page:
        source_page_token = esprima.tokenize(HTML(driver.page_source).xpath('//script[not(@src)]/text()')[0])
        if not glb.esprima_token_match(source_page_token, page_pattern['location']):
            accept_page = False
            logging.warning(f'page changed: location')
            notify(f'page changed: location', 'please check page code')
            driver.close()
            return
    sleep(10)
    driver.execute_script(f'''
        $('#dqszdmc').val('{''.join(region_name)}');
        $('#dqszddm').val('{region_code[-1]}');
    ''')
    sleep(5)

    if accept_page:
        driver.find_element(By.XPATH, "//button[text()='提交']").click()
        sleep(5)
        if driver.find_elements(By.XPATH, "//div[text()='保存数据成功']"):
            logging.warning(f'success: {account["account-id"]}')
        else:
            logging.warning(f'submit failed: {account["account-id"]} <<<{driver.page_source=}>>>')
            notify('submit failed', f'{account["account-id"]}')
    driver.close()


def run(wait=False):
    threads = []
    submit_catch(config['accounts'][0], True)
    for i, account in enumerate(config['accounts'][1:]):
        thread = Thread(target=submit_catch, args=(account, False))
        if wait:
            threads.append(thread)
        thread.start()
    for t in threads:
        t.join()


def submit_catch(*args, **kwargs):
    success, values = glb.run_func_catch(submit, *args, **kwargs)
    if not success:
        notify('error:', values)


def notify(title, content):
    glb.client.send_request(
        'post', 'https://www.pushplus.plus/send', json={
            'token': config['notification']['token'],
            'title': f'health information reporting: {title}',
            'content': str(content),
            'template': 'markdown',
        }
    )


def base64_to_int(string):
    return int(b64decode(string).hex(), 16)


def main():
    if run_immediately:
        run(wait=True)
        logging.warning('immediately running finished')
    scheduler = BlockingScheduler(job_defaults={'misfire_grace_time': 3600, 'coalesce': True})
    scheduler.add_job(run, 'cron', hour=7)
    scheduler.add_job(run, 'cron', hour=12)
    scheduler.add_job(run, 'cron', hour=19, minute=30)
    scheduler.start()


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
