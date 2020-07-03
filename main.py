import json
import logging
from base64 import b64decode, b64encode
from random import random
from time import time, sleep
from threading import Thread

import requests
import rsa
import yaml
from lxml.etree import HTML
from apscheduler.schedulers.background import BlockingScheduler

logging.basicConfig(format='%(asctime)s %(message)s')
with open('config.private.yaml') as io:
    config = yaml.safe_load(io)

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


def submit(account):
    sleep(random() * 60 * 30)
    session = requests.Session()
    session.headers.update(headers)

    # session.get('http://fresh.ahau.edu.cn/yxxt-v5/web/xsLogin/login.zf;?rdt=web%2Fjkxxtb%2FtbJkxx')
    publicKey = session.get('http://fresh.ahau.edu.cn/yxxt-v5/xtgl/login/getPublicKey.zf',
                            params={'time': int(round(time() * 1000))}).json()

    def base64ToInt(string):
        return int(b64decode(string).hex(), 16)

    publicKey = rsa.PublicKey(base64ToInt(publicKey['modulus']), base64ToInt(publicKey['exponent']))
    data = {
        'zhlx': b64encode(rsa.encrypt('xsxh'.encode(), publicKey)).decode(),
        'zh': b64encode(rsa.encrypt(account['student-id'].encode(), publicKey)).decode(),
        'mm': b64encode(rsa.encrypt(account['password'].encode(), publicKey)).decode(),
    }

    sleep(random() * 5)
    loginJson = session.post('http://fresh.ahau.edu.cn/yxxt-v5/web/xsLogin/checkLogin.zf',
                             data={'dldata': b64encode(json.dumps(data).encode()).decode()}).json()
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
    region = account['region']
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


def run():
    print()
    for account in config['accounts']:
        Thread(target=submit, args=(account,)).start()


scheduler = BlockingScheduler()
scheduler.add_job(run, 'cron', hour=7)
scheduler.start()
