from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from bson import ObjectId
from typing import List
import markdown
import datetime
import asyncio
import random
import docker

from task import run_task
from tools import localtime, dt_format, remove_tag_a, cache, new_task, get_task, complete_task, get_login_info, login_get_a2, generate_weekly
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

templates.env.filters["localtime"] = localtime
templates.env.filters["dt_format"] = dt_format
templates.env.filters["remove_tag_a"] = remove_tag_a


# 在应用程序启动之前运行的函数
@app.on_event("startup")
async def startup_event():
    print('启动定时任务')
    asyncio.create_task(run_task())

            
@app.get("/", response_class=HTMLResponse)
@cache(10)
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

            
@app.get("/rank", response_class=HTMLResponse)
async def rank(request: Request, start: str = None, end: str = None):
    '''排行榜'''

    now = localtime(datetime.datetime.now())
    recent_30_days = now - datetime.timedelta(days=30)
    recent_90_days = now - datetime.timedelta(days=90)
    recent_365_days = now - datetime.timedelta(days=365)
    try:
        start = localtime(datetime.datetime.strptime(start, '%Y-%m-%d'))
    except:
        start = localtime(datetime.datetime(2010,4,25))
    try:
        end = localtime(datetime.datetime.strptime(end, '%Y-%m-%d'))
    except:
        end = now


    topics = await db.topic.find({
        "date": {
            "$gte": start,
            "$lt": end
        }
    }).sort("score", -1).limit(100).to_list(100)
    
    replys = await db.reply.find({
        "date": {
            "$gte": start,
            "$lt": end
        }
    }).sort("thank", -1).limit(100).to_list(100)

    data = {
        'request': request,
        'start': start,
        'end': end,
        'recent_30_days': recent_30_days,
        'recent_90_days': recent_90_days,
        'recent_365_days': recent_365_days,
        'topics': topics,
        'replys': replys,
    }

    return templates.TemplateResponse("rank.html", data)


@app.get("/weekly/md", response_class=HTMLResponse)
async def weekly(request: Request):

    today = localtime(datetime.datetime.now()).replace(hour=0, minute=0, second=0)
    saturday = today - datetime.timedelta(days=(today.weekday() + 2))
    
    title, content = await generate_weekly(saturday)
    
    data = {
        'request': request,
        'markdown': f'### { title }  \n' + content
    }
    return templates.TemplateResponse("weeklyMarkdown.html", data)


@app.get("/weekly", response_class=HTMLResponse)
async def weekly(request: Request):

    weeklys = await db.weekly.find().sort('_id', -1).limit(10).to_list(10)
    
    data = {
        'request': request,
        'weeklys': weeklys
    }
    return templates.TemplateResponse("weeklyList.html", data)


@app.get("/weekly/detail/{weekly_id}", response_class=HTMLResponse)
async def weekly(weekly_id: str, request: Request):

    weekly = await db.weekly.find_one({'_id': ObjectId(weekly_id)})
    content = markdown.markdown(weekly['content'])
    user_agent = request.headers.get("User-Agent")
    if "Mobile" in user_agent:
        content = content.replace('&emsp;', '')
    data = {
        'request': request,
        'weekly': weekly,
        'content': content
    }
    return templates.TemplateResponse("weeklyDetail.html", data)


@app.get("/weekly/atom.xml", response_class=HTMLResponse)
async def weekly_atom(request: Request):

    today = localtime(datetime.datetime.now()).replace(hour=0, minute=0, second=0)
    weeklys = await db.weekly.find().sort('_id', -1).limit(10).to_list(10)
    for i in weeklys:
        i['content'] = markdown.markdown(i['content'])
    data = {
        'request': request,
        'updated': datetime.datetime.today().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'weeklys': weeklys
    }
    return templates.TemplateResponse("weekly.xml", data, media_type="application/atom+xml; charset=UTF-8")


@app.get("/a2", response_class=HTMLResponse)
async def get_a2():
    
    info = await get_login_info()
    html = f'<img src="data:image/png;base64,{ info["img"]}">'

    html += '<form method="GET" action="/a2/result">'
    html += '<input type="text" name="captcha" placeholder="验证码">'
    html += '<input type="text" name="pwd" placeholder="vPlus 密码">'
    html += f'<input type="hidden" name="once" value="{info["once"]}">'
    html += f'<input type="hidden" name="session" value="{info["session"]}">'
    html += f'<input type="hidden" name="u" value="{info["tokens"][0]}">'
    html += f'<input type="hidden" name="p" value="{info["tokens"][1]}">'
    html += f'<input type="hidden" name="o" value="{info["tokens"][2]}">'
    html += '<input type="submit">'
    html += '</form>'
    
    return HTMLResponse(html)

@app.get("/a2/result")
async def post_a2(captcha: str, pwd: str, once: str, session: str, u: str, p: str, o: str):
    a2 = await login_get_a2(captcha, pwd, once, session, u, p, o)
    return str(a2)
            
@app.get("/store", response_class=HTMLResponse)
async def store(request: Request):
    styles = await db.style.find().limit(100).to_list(100)
    data = {
        'request': request,
        'styles': styles
    }
    return templates.TemplateResponse("store.html", data)

@app.get("/style/{style_name}", response_class=HTMLResponse)
@cache(3600)
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

    return await get_task()


@app.post("/api/error/info", response_model=SuccessResponse, include_in_schema=False)
async def error_info(error: ErrorReport) -> SuccessResponse:
    '''错误上报'''
    await db.error.insert_one(error.dict())
    return SuccessResponse()


@app.get("/logs", response_class=StreamingResponse)
async def logs():
    '''请求日志'''

    client = docker.DockerClient(base_url='unix:///var/run/docker.sock')
    for container in client.containers.list():
        if 'fastapi' in container.name:
            log_stream = container.logs(stream=True, follow=True, tail=100)
            return StreamingResponse(log_stream, media_type="text/plain")
    return None
