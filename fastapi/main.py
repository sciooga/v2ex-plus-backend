from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import motor.motor_asyncio
from bson import ObjectId
from model import *
import datetime
import aiohttp
import random
import re


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

def localtime(date):
    """Custom filter"""
    return date.astimezone(datetime.timezone(datetime.timedelta(hours=8)))

templates.env.filters["localtime"] = localtime

client = motor.motor_asyncio.AsyncIOMotorClient('mongodb://mongo')
db = client.V2EX


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    '''各类主题列表及爬虫信息'''
    # await db.reply.delete_many({'content': {'$regex': r'div class="show-reply"'}})

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
        'topic_total': await db.topic.count_documents({}),
        # 超 90 天未爬取主题数
        'topic_recent_90days_total': await db.topic.count_documents({
            'spiderTime': {'$lte': datetime.datetime.now() - datetime.timedelta(days=90)}
        }),
        'cursor': (await db.info.find_one())['cursor'],
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
    return map(lambda x: x+1, range(int(bool(num % page_num)) + num//page_num))


async def new_task(id: int, page: int):
    '''新建爬虫任务'''
    if not await db.task.find_one({'id': id, 'page': page}):
        await db.task.insert_one({
            'id': id,
            'page': page,
            'distribute_time': None,
            'complete_time': None,
        })


async def get_task():
    '''获取爬虫任务（分配）'''
    task = await db.task.find_one_and_update({
        'distribute_time': None
    }, {
        '$set': {
            'distribute_time': datetime.datetime.now()
        }
    })
    if task:
        url = '/t/%s?page=%s' % (task['id'], task['page'])
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
    # return Task(sign='',id=0,page=0,url='')
    await db.task.delete_many({
        'complete_time': {'$ne': None},
        'distribute_time': {'$ne': None}}
    )
    task = await get_task()
    if task:
        return task

    await db.info.update_one({}, {
        '$inc': {
            'cursor': 100
        }
    }, upsert=True)

    # TEMP: 按顺序爬取 1 到最新主题，每次取 100 个，只爬第一页，爬完一轮后不再执行
    latest_topic = await db.topic.find_one(sort=[('id', -1)])
    info = await db.info.find_one()
    if info['cursor'] <= latest_topic['id'] - 3000:
        for i in range(info['cursor']-100, info['cursor']):
            await new_task(i, 1)

    # 最久没更新的 10 个主题
    topic_oldest = await db.topic.find().sort("spiderTime").limit(10).to_list(10)
    for i in topic_oldest:
        for page in page_range(i['reply']):
            await new_task(i['id'], page)

    # 网站最近更新 https://www.v2ex.com/changes
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

            for page in page_range(reply_num, 100):
                await new_task(id, page)

    task = await get_task()
    if task:
        return task


@app.post("/api/error/info", response_model=SuccessResponse)
async def error_info(error: ErrorReport) -> SuccessResponse:
    '''错误上报'''
    await db.error.insert_one(error.dict())
    return SuccessResponse()
