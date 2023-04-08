from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List
import datetime
import asyncio
import random

from task import run_task
from tools import remove_tag_a, new_task, get_task, complete_task, generate_weekly
from database import db
from model import SuccessResponse, Reply, Topic, Task, ErrorReport


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

templates.env.filters["localtime"] = lambda x: x.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
templates.env.filters["remove_tag_a"] = remove_tag_a


# 在应用程序启动之前运行的函数
@app.on_event("startup")
async def startup_event():
    print('启动定时任务')
    asyncio.create_task(run_task())

            
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    '''各类主题列表及爬虫信息'''

    days = list(range(1, 8))
    for i in range(10):
        days.append(random.randint(8,365*3))

    topics = []
    # 每天前三的主题且得分高于 8000 分
    for i in days:
        day = datetime.datetime.now() - datetime.timedelta(days=i)
        topics += (await db.topic.find({
            "date": {
                "$gte": day.replace(hour=0, minute=0, second=0),
                "$lt": day.replace(hour=23, minute=59, second=59)
            }
        }).sort("score", -1).limit(3).to_list(3))
    
    replys = []
    # 每天前三的回复
    for i in days:
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
        # 近一月超三天未爬取主题数
        'topic_recent_total': await db.topic.count_documents({
            'date': {'$gte': datetime.datetime.now() - datetime.timedelta(days=30)},
            'spiderTime': {'$lte': datetime.datetime.now() - datetime.timedelta(days=3)}
        }),
        # 超两周未爬取主题数
        'topic_recent_2w_total': await db.topic.count_documents({
            'spiderTime': {'$lte': datetime.datetime.now() - datetime.timedelta(days=14)}
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


@app.get("/weekly", response_class=HTMLResponse)
async def weekly(request: Request):
    
    title, content = await generate_weekly()
    
    data = {
        'request': request,
        'markdown': f'### { title }  \n' + content
    }
    return templates.TemplateResponse("weekly.html", data)

            
@app.get("/store", response_class=HTMLResponse)
async def store(request: Request):
    styles = await db.style.find().limit(100).to_list(100)
    data = {
        'request': request,
        'styles': styles
    }
    return templates.TemplateResponse("store.html", data)

            
@app.get("/style/{style_name}", response_class=HTMLResponse)
async def style(style_name):
        
    style = await db.style.find_one({'github': style_name})
    return HTMLResponse(style['css'], media_type="text/css")


@app.get("/api/topic/recommend", response_model=List[Topic])
async def topic_recommend() -> List[Topic]:
    '''推荐主题'''
    topics = await db.topic.find({
        'date': {
            '$gte': datetime.datetime.now() - datetime.timedelta(days=7)
        }
    }).sort("score", -1).limit(50).to_list(100)
    topics = random.sample(list(topics), 10)
    return list(map(dict, topics))


@app.get("/api/reply/recommend", response_model=List[Reply])
async def topic_recommend() -> List[Reply]:
    '''推荐回复'''
    replys = await db.reply.find({
        'date': {
            '$gte': datetime.datetime.now() - datetime.timedelta(days=7)
        }
    }).sort("thank", -1).limit(50).to_list(100)
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
        if '<div class="show-reply">' in i['content']:
            continue
        if '的这条回复发送感谢' in i['content']:
            continue
        await db.reply.find_one_and_update({'id': i['id']}, {"$set": i}, upsert=True)
    if (task != 'undefined'):
        await complete_task(task)
    return SuccessResponse()


@app.get("/api/topic/task", response_model=Task, include_in_schema=False)
async def topic_task() -> Task:
    '''获取爬取任务'''
    # return Task(sign='',id=0,page=1,url='')

    task = await get_task()
    if task:
        return task
    else:
        return Task(sign='',id=0,page=0,url='')


@app.post("/api/error/info", response_model=SuccessResponse, include_in_schema=False)
async def error_info(error: ErrorReport) -> SuccessResponse:
    '''错误上报'''
    await db.error.insert_one(error.dict())
    return SuccessResponse()
