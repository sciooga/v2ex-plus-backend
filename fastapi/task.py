from functools import wraps
import traceback
import datetime
import asyncio
import aiohttp
import re

from tools import page_range, new_task, generate_weekly
from database import db

TASKS = []
def bg_task(s: int):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            while True:
                try:
                    await func(*args, **kwargs)
                except Exception as e:
                    print('='*20)
                    print(func.__name__)
                    print(e)
                    traceback.print_exc()
                    print('='*20)
                await asyncio.sleep(s)
        TASKS.append(wrapper)
        return wrapper
    return decorator

async def run_task():
    for func in TASKS:
        asyncio.create_task(func())


@bg_task(10)
async def generate_task():
    '''定时任务: 生成长时间未更新主题的爬取任务'''

    print('生成长时间未更新主题的爬取任务')

    if await db.task.count_documents({'distribute_time': None}) >= 200:
        return

    # 最久没更新的 1000 个主题
    topic_oldest = await db.topic.find().sort("spiderTime").limit(1000).to_list(1000)
    for i in topic_oldest:
        for page in page_range(i['reply']):
            await new_task(i['id'], page, 'oldest')

    # 最近一个月的 100 个主题
    topic_recent = await db.topic.find({
            'date': {'$gte': datetime.datetime.now() - datetime.timedelta(days=30)}
        }).sort("spiderTime").limit(100).to_list(100)

    for i in topic_recent:
        for page in page_range(i['reply']):
            await new_task(i['id'], page, 'recent')


@bg_task(300)
async def topic_change():
    '''定时任务: 网站最近更新 https://www.v2ex.com/changes'''

    print('获取最新更新主题')
    async with aiohttp.request('GET', 'https://www.v2ex.com/changes') as r:
        topic_list = re.findall(r'/t/(\d+?)#reply(\d+)', await r.text())
        topic_list = list(set(topic_list))  # 去重
        for id, reply_num in topic_list:
            id = int(id)
            reply_num = int(reply_num)
            topic = await db.topic.find_one({'id': id})
            # 排除评论无变化
            if topic and topic['reply'] == reply_num:
                continue

            for page in page_range(reply_num):
                await new_task(id, page, 'change')


@bg_task(60)
async def delete_task():
    '''定时任务: 清除已完成的爬虫任务'''

    print('清除已完成的爬虫任务')
    await db.task.delete_many({
        'complete_time': {'$ne': None},
        # 'distribute_time': {'$ne': None}
    })
    # 重爬超时任务（任务要么完成要么报错进入 Error 处理）
    await db.task.update_many({
        'distribute_time': {'$lte': datetime.datetime.now() - datetime.timedelta(seconds=60)},
        'complete_time': None
    }, {
        '$set': {
           'distribute_time': None,
           'sign': 'reset'
        }
    })


@bg_task(60)
async def delete_error():
    '''定时任务: 清理错误'''
    print('清理错误')

    def get_id_page(url):
        result = re.search(r'/t/(\d+)', i['url'])
        if not result:
            return None, None
            
        topic_id = int(result.group(1))
        page = re.search(r'=(\d+)', i['url'])
        page = int(page.group(1)) if page else 1
        return topic_id, page

    # 404 错误删除任务创建一个 0 分主题
    errors = await db.error.find({'error': {'$regex': r'错误码404'}}).to_list(1000)
    for i in errors:
        await db.error.delete_one({'_id': i['_id']})
        topic_id, page = get_id_page(i['url'])
        if topic_id:
            await db.task.delete_many({'id': topic_id})
            await db.topic.update_one(
                {'id': topic_id},
                {"$set": Topic(
                    spiderTime = datetime.datetime(2999,1,1),
                    date = datetime.datetime(2999,1,1),
                    id = topic_id, name = '', node = '',
                    author = '', avatar = '', reply = 0,
                    vote = 0, click = 0, collect = 0,
                    thank = 0, score = 0, content = '',
                    append = [], replys = [],
                ).dict()
            }, upsert=True)

    # 403、502、post 错误需要删除错误重爬一次
    for rekey in [r'错误码502', r'at post',r'错误码403']:
        errors = await db.error.find({'error': {'$regex': rekey}}).to_list(1000)
        for i in errors:
            await db.error.delete_one({'_id': i['_id']})
            topic_id, page = get_id_page(i['url'])
            if topic_id:
                await new_task(topic_id, page, rekey)

    # 其余错误（主要是 get 和 null）无法判断，大部分重爬可以解决
    errors = await db.error.find().to_list(1000)
    for i in errors:
        topic_id, page = get_id_page(i['url'])
        if not topic_id:
            # url 错误的直接删除
            await db.error.delete_one({'_id': i['_id']})
        # 发生错误之后主题更新过则删除错误 TODO 考虑小概率多页主题只是某页出错
        topic = await db.topic.find_one({'id': topic_id})
        if topic and i['time'] <= topic['spiderTime']:
            await db.error.delete_one({'_id': i['_id']})
        if await db.error.count_documents({'url': {'$regex': r'/t/%s\?p=%s' % (topic_id, page)}}) < 3:
            await new_task(topic_id, page, rekey)
        else:
            print('主题需要人工处理错误', 'https://v2ex.com/t/%s?p=%s' % (topic_id, page))


@bg_task(30)
async def weekly_task():
    # 每周日早上 10:00 自动发布周报
    today = datetime.datetime.now()
    if today.weekday() != 6 or today.hour != 10 or today.minute > 5:
        print('没到时间')
        return

    title, content = await generate_weekly()

    weekly = await db.weekly.find_one({'title': title})
    if weekly:
        print('周报已存在')
        return
    
    return
    print('发布周报')

    url = 'https://www.v2ex.com/write?node=share'
    A2 = (await db.info.find_one())['A2']
    cookies = {'A2': A2}
    async with aiohttp.ClientSession(cookies=cookies) as session:
        async with session.get(url) as resp:
            result = re.search(r'/signout\?once=(\d+)', await resp.text())
            if not result:
                return 'A2 过期' + A2
            once = int(result.group(1))
        payload = {
            'title': title,
            'content': content,
            'syntax': 'markdown',
            'once': once
        }
        async with session.post(url, data=payload) as resp:
            result = re.search(r'/t/(\d+)#reply0', await resp.text())
            if not result:
                return '发布失败'
            topic_id = result.group(1)
        
    await db.weekly.insert_one({
        'title': title,
        'content': content,
        'id': topic_id
    })