import datetime

from tools import remove_tag_a

async def generate_weekly():
    # 获取上周六至周五的周报
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