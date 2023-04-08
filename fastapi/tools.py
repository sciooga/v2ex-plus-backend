from bson import ObjectId
import datetime
import random
import re

from database import db
from model import Task


def remove_tag_a(html):
    return re.sub('<a .*?>|</a>', '', html)

# 内存缓存 过期数据只有重启才会清理
def cache(expiration_time=60):
    cached_results = {}

    def wrapper(func):
        def inner(*args):
            if args in cached_results:
                result, timestamp = cached_results[args]
                if time.time() - timestamp < expiration_time:
                    return result
            result = func(*args)
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
        return None
    task = await db.task.find_one_and_update({
        'distribute_time': None,
    }, {
        '$set': {
            'distribute_time': datetime.datetime.now()
        }
    }, sort=[('_id', 1)])
    if task:
        url = '/t/%s?p=%s' % (task['id'], task['page'])
        return Task(
            sign=str(task['_id']),
            id=task['id'],
            page=task['page'],
            url=url
        )
    else:
        return None


async def complete_task(sign):
    '''完成爬虫任务'''
    await db.task.find_one_and_update({
        '_id': ObjectId(sign)
    }, {
        '$set': {
            'complete_time': datetime.datetime.now()
        }
    })