
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Literal, Any, Union
from datetime import datetime


class SuccessResponse(BaseModel):
    code: int = Field(description='响应状态码', default=0)
    msg: str = Field(description='状态码说明', default='ok')
    data: Any = Field(description='数据')


class Reply(BaseModel):
    spiderTime: datetime = Field(description='爬取时间')
    topicId: int = Field(description='主题 ID')
    topicPage: int = Field(description='主页页码')
    id: int = Field(description='回复 ID')
    author: str = Field(description='作者')
    avatar: str = Field(description='头像')
    date: datetime = Field(description='发布日期')
    thank: int = Field(description='感谢')
    content: str = Field(description='评论内容')


class Topic(BaseModel):
    spiderTime: datetime = Field(description='爬取时间')
    id: int = Field(description='主题 ID')
    name: str = Field(description='标题')
    node: str = Field(description='节点')
    author: str = Field(description='作者')
    avatar: str = Field(description='头像')
    date: datetime = Field(description='发布日期')
    reply: int = Field(description='回复数')
    vote: int = Field(description='投票数')
    click: int = Field(description='点击量')
    collect: int = Field(description='收藏数')
    thank: int = Field(description='感谢数')
    score: int = Field(description='得分')

    content: str = Field(description='正文内容')
    append: List[str] = Field(description='追加内容')
    replys: Union[List[Reply], None] = Field(description='获赞回复')


class Task(BaseModel):
    sign: str = Field(description='任务 ID')
    id: int = Field(description='主题 ID')
    page: int = Field(description='页码')
    url: str = Field(description='爬取地址')


class ErrorReport(BaseModel):
    type: Literal['read', 'task'] = Field(description='错误类型')
    url: str = Field(description='错误地址')
    error: str = Field(description='错误内容')
    time: datetime = Field(description='报错时间')
