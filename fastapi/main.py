from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import motor.motor_asyncio
from bson import ObjectId
from model import *
import datetime
import asyncio
import aiohttp
import random
import time
import re


client = motor.motor_asyncio.AsyncIOMotorClient('mongodb://mongo')
db = client.V2EX


app = FastAPI(
    title="V2EX Plus 扩展后端服务",
    description='为扩展提供 vDaily 数据支撑',
    version="1.0.0",
    terms_of_service="https://chrome.google.com/webstore/detail/v2ex-plus/daeclijmnojoemooblcbfeeceopnkolo",
    contact={
        "name": "sciooga",
        "url": "https://huguotao.com",
        "email": "sciooga@gmail.com",
    },
    license_info={
        "name": "GPL-3.0",
        "url": "https://www.gnu.org/licenses/gpl-3.0.en.html",
    },)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def remove_tag_a(html):
    return re.sub('<a .*?>|</a>', '', html)

templates.env.filters["localtime"] = lambda x: x.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
templates.env.filters["remove_tag_a"] = remove_tag_a

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

async def bg_task(s: int, func: callable):
    while True:
        try:
            await func()
        except Exception as e:
            print(e)
        await asyncio.sleep(s)

async def generate_task():
    '''定时任务: 生成长时间未更新主题的爬取任务'''

    print('生成长时间未更新主题的爬取任务')

    if await db.task.count_documents({'distribute_time': None}) >= 500:
        return

    # 最久没更新的 1000 个主题
    topic_oldest = await db.topic.find().sort("spiderTime").limit(1000).to_list(1000)
    for i in topic_oldest:
        for page in page_range(i['reply']):
            await new_task(i['id'], page, 'oldest')

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

async def delete_task():
    '''定时任务: 清除已完成的爬虫任务'''

    print('清除已完成的爬虫任务')
    await db.task.delete_many({
        'complete_time': {'$ne': None},
        # 'distribute_time': {'$ne': None}
    })

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


# 在应用程序启动之前运行的函数
@app.on_event("startup")
async def startup_event():
    print('启动定时任务')
    asyncio.create_task(bg_task(10, generate_task))
    asyncio.create_task(bg_task(300, topic_change))
    asyncio.create_task(bg_task(60, delete_task))
    asyncio.create_task(bg_task(60, delete_error))


@app.get("/api/test")
async def test():

    # 重爬所有任务
    await db.task.update_many({
            'distribute_time': {'$lte': datetime.datetime.now() - datetime.timedelta(seconds=60)},
            'complete_time': None
        }, {'$set': {'distribute_time': None, 'sign': 'reset'}})
    return 1

            
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    '''各类主题列表及爬虫信息'''

    topics = []
    # 最近 7 天每天前三的主题且得分高于 8000 分
    for i in range(1, 8):
        day = datetime.datetime.now() - datetime.timedelta(days=i)
        topics += (await db.topic.find({
            "date": {
                "$gte": day.replace(hour=0, minute=0, second=0),
                "$lt": day.replace(hour=23, minute=59, second=59)
            }
        }).sort("score", -1).limit(3).to_list(3))
    
    replys = []
    # 最近 7 天每天前三的回复
    for i in range(1, 8):
        day = datetime.datetime.now() - datetime.timedelta(days=i)
        replys += (await db.reply.find({
            "date": {
                "$gte": day.replace(hour=0, minute=0, second=0),
                "$lt": day.replace(hour=23, minute=59, second=59)
            }
        }).sort("thank", -1).limit(3).to_list(3))

    data = {
        'request': request,
        'topics': topics,
        'replys': replys,
        # 主题总数
        # 'topic_total': await db.topic.count_documents({}),
        # 超 90 天未爬取主题数
        'topic_recent_90days_total': await db.topic.count_documents({
            'spiderTime': {'$lte': datetime.datetime.now() - datetime.timedelta(days=90)}
        }),
        # 'cursor': (await db.info.find_one())['cursor'],
        'latest_topic_id': (await db.topic.find_one(sort=[('id', -1)]))['id'],
        # 任务总数
        'task_total': await db.task.count_documents({}),
        # 未分配任务总数
        'task_not_distribute_total': await db.task.count_documents({'distribute_time': None}),
        # 未完成任务总数
        'task_not_complete_total': await db.task.count_documents({'complete_time': None}),
        # 分配后未完成任务总数
        'task_distribute_but_not_complete_total': await db.task.count_documents({
            'distribute_time': {'$lte': datetime.datetime.now() - datetime.timedelta(seconds=60)},
            'complete_time': None
        }),
        # 待处理错误数
        'error_total': await db.error.count_documents({}),
    }

    return templates.TemplateResponse("index.html", data)


@app.get("/api/topic/recommend", response_model=List[Topic])
async def topic_recommend() -> List[Topic]:
    '''推荐主题'''
    topics = await db.topic.find({
        'date': {
            '$gte': datetime.datetime.now() - datetime.timedelta(days=3)
        }
    }).sort("score", -1).limit(30).to_list(30)
    topics = random.sample(list(topics), 10)
    return list(map(dict, topics))


@app.get("/api/reply/recommend", response_model=List[Reply])
async def topic_recommend() -> List[Reply]:
    '''推荐回复'''
    replys = await db.reply.find({
        'date': {
            '$gte': datetime.datetime.now() - datetime.timedelta(days=3)
        }
    }).sort("thank", -1).limit(30).to_list(30)
    replys = random.sample(list(replys), 10)
    for i in replys:
        i['content'] = remove_tag_a(i['content'])
    return list(map(dict, replys))


@app.post("/api/topic/info", response_model=SuccessResponse)
async def topic_info(task: str, topic: Topic) -> SuccessResponse:
    '''提交主题信息'''
    topic = topic.dict()
    replys = topic.pop('replys')
    await db.topic.update_one({'id': topic['id']}, {"$set": topic}, upsert=True)
    # TEMP 临时排除浏览状态提交的回复（其他插件影响内容）
    for i in replys:
        if '<div class="show-reply">' not in i['content']:
            await db.reply.find_one_and_update({'id': i['id']}, {"$set": i}, upsert=True)
    if (task != 'undefined'):
        await complete_task(task)
    return SuccessResponse()


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


@app.get("/api/topic/task", response_model=Task)
async def topic_task() -> Task:
    '''获取爬取任务'''
    # return Task(sign='',id=0,page=1,url='')

    task = await get_task()
    if task:
        return task
    else:
        return Task(sign='',id=0,page=0,url='')


@app.post("/api/error/info", response_model=SuccessResponse)
async def error_info(error: ErrorReport) -> SuccessResponse:
    '''错误上报'''
    await db.error.insert_one(error.dict())
    return SuccessResponse()
