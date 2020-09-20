import argparse
import json
import logging
from base64 import b64decode, b64encode
from random import random
from threading import Thread
from time import time, sleep

import requests
import rsa
import yaml
from apscheduler.schedulers.background import BlockingScheduler
from lxml.etree import HTML

region = ['340000', '340100', '340104', '安徽省', '合肥市', '蜀山区']

logging.basicConfig(format='%(asctime)s %(message)s')
with open('config.private.yaml') as io:
    config = yaml.safe_load(io)

parser = argparse.ArgumentParser()
parser.add_argument('-i', action='store_true', help='立即执行')
args = parser.parse_args()
executeImmediately = args.i

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


def run():
    print()
    for account in config['accounts']:
        Thread(target=submit, args=(account,)).start()


def submit(account):
    if not executeImmediately:
        sleep(random() * 60 * 30)
    session = requests.Session()
    session.headers.update(headers)

    publicKey = sendRequest(
        session,
        requests.Request(
            'GET', 'http://fresh.ahau.edu.cn/yxxt-v5/xtgl/login/getPublicKey.zf',
            params={'time': int(round(time() * 1000))},
        ).prepare()
    ).json()

    def base64ToInt(string):
        return int(b64decode(string).hex(), 16)

    publicKey = rsa.PublicKey(base64ToInt(publicKey['modulus']), base64ToInt(publicKey['exponent']))
    data = {
        'zhlx': b64encode(rsa.encrypt('xsxh'.encode(), publicKey)).decode(),
        'zh': b64encode(rsa.encrypt(account['student-id'].encode(), publicKey)).decode(),
        'mm': b64encode(rsa.encrypt(account['password'].encode(), publicKey)).decode(),
    }

    sleep(random() * 5)
    loginJson = session.post(
        'http://fresh.ahau.edu.cn/yxxt-v5/web/xsLogin/checkLogin.zf',
        data={'dldata': b64encode(json.dumps(data).encode()).decode()}
    ).json()
    if loginJson['status'] != 'SUCCESS':
        logging.warning((account['student-id'], 'login failed: ', loginJson))
        return

    sleep(random() * 1)
    formHtml = session.get('http://fresh.ahau.edu.cn/yxxt-v5/web/jkxxtb/tbJkxx.zf').text
    data = {}
    for i in HTML(formHtml).xpath('//*[@id="jftbForm"]/input'):
        name = i.attrib.get('name')
        data[name] = i.attrib.get('value')
    data['tw'] = '36.{}'.format(int(random() * 8) + 1)
    data['dqszdmc'] = '/'.join(region[3:6])
    data['dqszsfdm'] = region[0]
    data['dqszsdm'] = region[1]
    data['dqszxdm'] = region[2]
    data['bz'] = ''
    data['ydqszsfmc'] = region[3]
    data['ydqszsmc'] = region[4]
    data['ydqszxmc'] = region[5]

    sleep(random() * 10)
    submitJson = session.post('http://fresh.ahau.edu.cn/yxxt-v5/web/jkxxtb/tbBcJkxx.zf', data=data).json()
    if submitJson['status'] == 'success':
        logging.warning((account['student-id'], 'success'))
    else:
        logging.warning((account['student-id'], 'submit failed: ', submitJson))


def sendRequest(session, preparedRequest):
    while True:
        try:
            response = session.send(preparedRequest, timeout=10)
            return response
        except Exception as e:
            print(e)
            sleep(60)


if executeImmediately:
    run()
else:
    scheduler = BlockingScheduler()
    scheduler.add_job(run, 'cron', hour=7)
    scheduler.add_job(run, 'cron', hour=12)
    scheduler.add_job(run, 'cron', hour=19, minute=30)
    scheduler.start()
