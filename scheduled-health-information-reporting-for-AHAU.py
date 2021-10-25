import json
import logging
from base64 import b64decode, b64encode
from pathlib import Path
from random import random, randrange
from threading import Thread
from time import time, sleep

import rsa
import yaml
from apscheduler.schedulers.background import BlockingScheduler

import glb

region_code = ['340000', '340100', '340104']
region_name = ['安徽省', '合肥市', '蜀山区']

logging.basicConfig(format='%(asctime)s %(message)s')
config_path = Path('config.private.yaml')
config = yaml.safe_load(config_path.read_text())

parser = glb.parser
parser.add_argument('-i', action='store_true', help='立即执行')
args = parser.parse_args()
run_immediately = args.i
glb.request_limits['ahau.edu.cn'] = glb.Limit(glb.SleepTime(range=[5, 30]))
glb.request_limits['pushplus.plus'] = glb.Limit(glb.SleepTime(time=20))


def run(wait=False):
    threads = []
    for account in config['accounts']:
        thread = Thread(target=submit, args=(account,))
        if wait:
            threads.append(thread)
        thread.start()
    for t in threads:
        t.join()


def submit(account):
    if not run_immediately:
        sleep(random() * 60 * 30)
    client = glb.Client(timeout=10)
    client.headers.update(headers)

    public_key = client.send_request(
        'get', 'http://fresh.ahau.edu.cn/yxxt-v5/xtgl/login/getPublicKey.zf',
        params={'time': int(round(time() * 1000))},
    ).json()
    public_key = rsa.PublicKey(base64_to_int(public_key['modulus']), base64_to_int(public_key['exponent']))
    login_data = {
        'zhlx': b64encode(rsa.encrypt('xsxh'.encode(), public_key)).decode(),
        'zh': b64encode(rsa.encrypt(account['student-id'].encode(), public_key)).decode(),
        'mm': b64encode(rsa.encrypt(account['password'].encode(), public_key)).decode(),
    }
    login_resp = client.send_request(
        'post', 'http://fresh.ahau.edu.cn/yxxt-v5/web/xsLogin/checkLogin.zf',
        data={'dldata': b64encode(json.dumps(login_data).encode()).decode()}
    ).json()
    if login_resp['status'] != 'SUCCESS':
        logging.warning(f'login failed: {account["student-id"]} {login_resp=}')
        notify('health information reporting: login failed', f'{account["student-id"]}')
        return

    form_html = client.send_request('get', 'http://fresh.ahau.edu.cn/yxxt-v5/web/jkxxtb/tbJkxx.zf').tree
    data = {}
    for i in form_html.xpath("//*[@id='jftbForm']//input"):
        data[i.get('name')] = i.get('value')
    for i in form_html.xpath("//*[@id='jftbForm']//textarea"):
        data[i.get('name')] = i.text
    data['tw'] = '36.{}'.format(randrange(4, 8))
    data['bz'] = ''
    data['dqszdmc'] = ''.join(region_name)
    data['dqszsfdm'], data['dqszsdm'], data['dqszxdm'] = region_code
    data['ydqszsfmc'], data['ydqszsmc'], data['ydqszxmc'] = region_name

    submit_resp = client.send_request(
        'post', 'http://fresh.ahau.edu.cn/yxxt-v5/web/jkxxtb/tbBcJkxx.zf', data=data
    ).json()
    if submit_resp['status'] == 'success':
        logging.warning(f'success: {account["student-id"]}')
    else:
        logging.warning(f'submit failed: {account["student-id"]} {submit_resp=}')
        notify('health information reporting: submit failed', f'{account["student-id"]}')


def notify(title, content):
    glb.client.send_request(
        'post', 'https://www.pushplus.plus/send', json={
            'token': config['notification']['token'],
            'title': title,
            'content': content,
            'template': 'markdown',
        }
    )


def base64_to_int(string):
    return int(b64decode(string).hex(), 16)


def main():
    if run_immediately:
        run(wait=True)
        logging.warning('immediately running finished')
    scheduler = BlockingScheduler()
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
