from functools import wraps
from bson import ObjectId
import datetime
import aiohttp
import random
import base64
import time
import re

from database import db
from model import Task


def localtime(dt):
    return dt.astimezone(datetime.timezone(datetime.timedelta(hours=8)))

def dt_format(dt, format = '%Y-%m-%d %H:%M:%S'):
    return dt.strftime(format)

def remove_tag_a(html):
    return re.sub('<a .*?>|</a>', '', html)


# 内存缓存 过期数据只有重启才会清理
def cache(expiration_time=60):
    cached_results = {}

    def wrapper(func):
        @wraps(func)
        async def inner(*args, **kwargs):
            if args in cached_results:
                result, timestamp = cached_results[args]
                if time.time() - timestamp < expiration_time:
                    return result
            result = await func(*args, **kwargs)
            cached_results[args] = (result, time.time())
            return result
        return inner
    return wrapper


def page_range(num: int, page_num: int = 100) -> list:
    '''通过数量及分页数生成页码列表'''
    if num:
        return range(1, int(bool(num % page_num)) + num//page_num + 1)
    else:
        return [1]


async def new_task(id: int, page: int, task_type: str):
    '''新建爬虫任务'''

    await db.task.update_one(
        {'id': id, 'page': page},
        {"$set": {
            'id': id,
            'page': page,
            'distribute_time': None,
            'complete_time': None,
            'type': task_type,
        }},
    upsert=True)


async def get_task():
    '''获取爬虫任务（分配）'''
    # 更新速度可以放慢一半
    if random.random() >= 0.3:
        return Task(sign='',id=0,page=0,url='')

    task = await db.task.find_one_and_update({
        'distribute_time': None,
    }, {
        '$set': {
            'distribute_time': datetime.datetime.now()
        }
    }, sort=[('_id', 1)])
    
    if not task:
        return Task(sign='',id=0,page=0,url='')

    url = '/t/%s?p=%s' % (task['id'], task['page'])
    return Task(
        sign=str(task['_id']),
        id=task['id'],
        page=task['page'],
        url=url
    )


async def complete_task(sign):
    '''完成爬虫任务'''
    await db.task.find_one_and_update({
        '_id': ObjectId(sign)
    }, {
        '$set': {
            'complete_time': datetime.datetime.now()
        }
    })


async def send_msg_to_tg(message):
    '''发送消息到 tg 群'''
    
    print(message)
    bot_token = "6166416562:AAEoN6dIlqM0Lf13lhnOEZyzcwC1fR4YKVM" # token 没什么价值
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": "-203039215",
        "text": message
    }

    async with aiohttp.request('POST', url, json=payload) as r:
        return await r.json()


headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/33.0.1750.152 Safari/537.36",
    "Host": "www.v2ex.com",
    "Referer": "https://www.v2ex.com/signin",
    "Origin": "https://www.v2ex.com"
}

async def get_login_info():
    '''获取 V 站登录信息'''

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get('https://v2ex.com/signin') as rep:
            html = await rep.text()
            # 获取 once
            once = re.search(r"value=\"(\d+?)\" name=\"once\"", html)
            if once:
                once = str(once.group(1))
            else:
                return '登陆页面无法获取到 once' + html

            # 获取tokens,cookies
            tokens = re.findall('class="sl" name="(.*?)"', html)
            cookies = session.cookie_jar.filter_cookies('https://v2ex.com')

        # 请求验证码
        async with session.get('https://v2ex.com/_captcha?once=' + once) as rep:
            # 得到验证码图片的base64编码
            img_content = await rep.read()
            img_b64 = base64.b64encode(img_content).decode('ascii')
        
        print(cookies)
        return {
            'once': once,
            'tokens': tokens,
            'session': cookies['PB3_SESSION'].value,
            'img': img_b64
        }

async def login_get_a2(captcha, pwd, once, session, u, p, o):
    '''登录获取 A2'''

    cookies = {
        'PB3_SESSION': session
    }

    payload = {
        u: 'v2explus@gmail.com',
        p: pwd,
        o: captcha,
        'once': once,
        'next': '/'
    }
    
    async with aiohttp.ClientSession(headers=headers, cookies=cookies) as session:
        async with session.post('https://v2ex.com/signin', params=payload, allow_redirects=True) as r:
            html = await r.text()

            cookies = session.cookie_jar.filter_cookies('https://v2ex.com')
            A2 = cookies.get('A2')
            if not A2:
                return '登录失败' + html
            
    db.info.update_one({}, {
        '$set': {
            'A2': A2.value,
            'A2_update': datetime.datetime.now()
        }
    })
    await send_msg_to_tg('A2 更新成功')
    return '操作成功，A2 更新成功'



async def generate_weekly(saturday):
    '''获取周六至周五的周报'''
    
    friday = saturday + datetime.timedelta(days=6,hours=23,minutes=59) 

    title = f'✨ V2EX 周报 本周热门主题及高赞回复 {saturday:%m.%d}-{friday:%m.%d}'

    topics = await db.topic.find({
        "date": {"$gte": saturday, "$lt": friday}
    }).sort("score", -1).limit(30).to_list(30)
    
    replys = await db.reply.find({
        "date": {"$gte": saturday, "$lt": friday}
    }).sort("thank", -1).limit(30).to_list(30)

    content = '🙋‍♂️ vDaily 每周日早 9:00 为您统计本周内的热门主题和高赞回复  \n\n'
    content += '🛠️ 推荐使用站内流行的浏览器扩展: [V2EX Plus](https://chrome.google.com/webstore/detail/v2ex-plus/daeclijmnojoemooblcbfeeceopnkolo)  \n'
    content += '***\n'
    content += '### 🎉 热门主题\n'
    for i in topics:
        info = f'{i["author"]} · {i["node"]} · {localtime(i["date"]):%Y-%m-%d}'
        content += f'> [{i["score"]: >6} ➰ **{i["name"]}**  \n&emsp;&emsp;&emsp;&emsp;&emsp;&ensp;{info}](/t/{i["id"]})  \n\n'
        

    replys = await db.reply.find({
        "date": {"$gte": saturday, "$lt": friday}
     }).sort("thank", -1).limit(15).to_list(15)

    content += '***\n'
    content += '### 💕 高赞回复\n'

    for i in replys:
        url = f'/t/{i["topicId"]}?p={i["topicPage"]}#r_{i["id"]}'
        reply = remove_tag_a(i['content']).replace("<br>", " ") # 移除 <a> <br>
        reply = re.sub(r'(.+imgur.+)(\.)', r'\1s.', reply) # 调整 imgur 大小
        info = f'{i["author"]} · {localtime(i["date"]):%Y-%m-%d}'
        content += f'> [{i["thank"]: >9} ➰ **{ reply }**  \n&emsp;&emsp;&emsp;&emsp;&emsp;&ensp;{info}]({ url })  \n\n'

    lastWeekly = await db.weekly.find_one({}, sort=[('_id', -1)])

    content += '***\n'
    content += f'🔗 回顾上一期周报: [{lastWeekly["title"]}](/t/{lastWeekly["id"]})  \n'
    content += '🌐 查看更多优质主题及回复: [V2EX 精选](https://vdaily.huguotao.com)  \n'
    content += '🥇 主题及回复排行榜: [V2EX 排行](https://vdaily.huguotao.com/rank)  \n'
    content += '⚙️ 到这里选择您喜欢的 V 站主题样式: [V2EX 样式商城](https://vdaily.huguotao.com/store)  \n'
    content += '📰 RSS 订阅: [Atom](https://vdaily.huguotao.com/weekly/atom.xml)  \n'
    content += '✉️ 欢迎任何交流及反馈: [sciooga@gmail.com](mailto:sciooga@gmail.com)  \n'
    content += '\n周末愉快，下周再见👋'
    return title, content
