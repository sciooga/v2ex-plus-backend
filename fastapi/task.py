from functools import wraps
import traceback
import datetime
import asyncio
import aiohttp
import re

from tools import localtime, page_range, new_task, send_msg_to_tg, generate_weekly
from model import Topic
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


@bg_task(30)
async def generate_task():
    '''定时任务: 生成长时间未更新主题的爬取任务'''

    print('生成长时间未更新主题的爬取任务')

    if await db.task.count_documents({'distribute_time': None}) >= 100:
        return

    # 最久没更新的 1000 个主题
    topic_oldest = await db.topic.find({
        'spiderTime': {'$lte': datetime.datetime.now() - datetime.timedelta(days=7)}
    }).sort("spiderTime").limit(1000).to_list(1000)
    for i in topic_oldest:
        for page in page_range(i['reply']):
            await new_task(i['id'], page, 'oldest')

    # 最近一个月的 100 个主题
    topic_recent = await db.topic.find({
            'date': {'$gte': datetime.datetime.now() - datetime.timedelta(days=30)},
            'spiderTime': {'$lte': datetime.datetime.now() - datetime.timedelta(hours=3)}
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


@bg_task(600)
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
            return
        # 发生错误之后主题更新过则删除错误 TODO 考虑小概率多页主题只是某页出错
        topic = await db.topic.find_one({'id': topic_id})
        if topic and i['time'] <= topic['spiderTime']:
            await db.error.delete_one({'_id': i['_id']})
        if await db.error.count_documents({'url': {'$regex': r'/t/%s\?p=%s' % (topic_id, page)}}) < 10:
            await new_task(topic_id, page, rekey)
        else:
            await send_msg_to_tg('主题需要人工处理错误 https://v2ex.com/t/%s?p=%s' % (topic_id, page))


# @bg_task(60*60*12)
async def a2_task():
    # 半天检查一次 A2 是否过期
    # 现在该任务暂不执行，因为无法绕过 cf 自动发帖，功能暂停
    print('检查 A2 是否过期')
    A2 = (await db.info.find_one())['A2']
    cookies = {'A2': A2}
    async with aiohttp.request('GET', 'https://v2ex.com/about', cookies=cookies) as r:
        result = re.search(r'/signout\?once=(\d+)', await r.text())

        if result:
            print('A2 状态正常')
        else:
            await send_msg_to_tg('A2 过期，请协助: https://vdaily.huguotao.com/a2')


# @bg_task(30)
async def weekly_task():
    # 每周日早上 9:00 自动发布周报
    # 现在该任务暂时不执行，替换为发布内部周报
    today = localtime(datetime.datetime.now())
    if today.weekday() != 6 or today.hour != 9 or today.minute > 5:
        print('没到发送周报的时间', today)
        return

    saturday = today.replace(hour=0, minute=0, second=0) - datetime.timedelta(days=(today.weekday() + 2))
    title, content = await generate_weekly(saturday)

    weekly = await db.weekly.find_one({'title': title})
    if weekly:
        print('周报已存在无需重新发送')
        return
    
    print('开始发布周报')

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
            'node_name': 'share',
            'once': once
        }
        async with session.post(url, data=payload) as resp:
            html = await resp.text()
            result = re.search(r'/t/(\d+)#reply0', html)
            if not result:
                print('发布失败')
                print(html)
                return
            topic_id = result.group(1)
    
    await db.weekly.insert_one({
        'title': title,
        'content': content,
        'id': topic_id,
        'date': datetime.datetime.now()
    })
    print(f'发布成功 https://v2ex.com/t/{topic_id}')


@bg_task(30)
async def weekly_predigest_task():
    # 每周日早上 9:00 自动发布周报（内部版）
    today = localtime(datetime.datetime.now())
    if today.weekday() != 6 or today.hour != 9 or today.minute > 5:
        print('没到发送周报的时间', today)
        return

    saturday = today.replace(hour=0, minute=0, second=0) - datetime.timedelta(days=(today.weekday() + 2))
    title, content = await generate_weekly(saturday)

    weekly = await db.weekly.find_one({'title': title})
    if weekly:
        print('周报已存在无需重新发送')
        return
    
    print('开始发布周报')
    
    await db.weekly.insert_one({
        'title': title,
        'content': content,
        'id': 934841, # 写死之前的周报
        'date': datetime.datetime.now()
    })
    print(f'发布成功')
