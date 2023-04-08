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
    

async def generate_weekly():
    # 获取上周六至周五的周报
    # TODO 自动增加往期链接
    today = datetime.datetime.now().replace(hour=0, minute=0, second=0)
    saturday = today - datetime.timedelta(days=(today.weekday() + 2))
    friday = saturday + datetime.timedelta(days=6,hours=23,minutes=59) 

    title = f'✨ V2EX 周报 本周热门主题及高赞回复 {saturday:%m.%d}-{friday:%m.%d}'

    topics = await db.topic.find({
        "date": {"$gte": saturday, "$lt": friday}
    }).sort("score", -1).limit(30).to_list(30)
    
    replys = await db.reply.find({
        "date": {"$gte": saturday, "$lt": friday}
    }).sort("thank", -1).limit(30).to_list(30)

    content = '🙋‍♂️ vDaily 为您统计了本周内的热门主题和高赞回复  \n\n'
    content += '🛠️ 推荐使用站内流行的浏览器扩展: [V2EX Plus](https://chrome.google.com/webstore/detail/v2ex-plus/daeclijmnojoemooblcbfeeceopnkolo)  \n'
    content += '⚙️ 到这里选择您喜欢的 V 站主题样式: [V2EX 样式商城](https://vdaily.huguotao.com/store)  \n'
    content += '***\n'
    content += '### 🎉 热门主题\n'
    for i in topics:
        info = f'{i["author"]} · {i["node"]} · {i["date"]:%Y-%m-%d}'
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
        info = f'{i["author"]} · {i["date"]:%Y-%m-%d}'
        content += f'> [{i["thank"]: >9} ➰ **{ reply }**  \n&emsp;&emsp;&emsp;&emsp;&emsp;&ensp;{info}]({ url })  \n\n'

    content += '***\n'
    content += '🔗 查看更多优质主题及回复: [V2EX 精选](https://vdaily.huguotao.com)  \n'
    content += '✉️ 欢迎任何交流及反馈: [sciooga@gmail.com](mailto:sciooga@gmail.com)  \n'
    content += '\n周末愉快，下周再见👋'
    return title, content