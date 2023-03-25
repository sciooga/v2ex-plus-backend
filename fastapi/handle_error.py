import asyncio
import motor.motor_asyncio
import re

# 遍历错误，依次处理已知错误
async def check_index():
    client = motor.motor_asyncio.AsyncIOMotorClient('mongodb://mongo')
    db = client['V2EX']
    cursor = db.error.find()
    async for i in cursor:
        print(i['url'])
        result = re.search(r'/t/(\d+)', i['url'])
        if not result:
            print('='*20, 'url 不正确', dict(i))
            await db.error.delete_one({'_id': i['_id']})
            continue


            
        topic_id = int(result.group(1))
        page = re.search(r'=(\d+)', i['url'])
        page = int(page.group(1)) if page else 1
        topic = await db.topic.find_one({'id': topic_id})
        if topic:
            await db.error.delete_one({'_id': i['_id']})
            print('topic 已存在 删除 错误')

        if '403' in i['error']:
            print('403')
            await db.error.delete_one({'_id': i['_id']})
            await db.task.insert_one({
                'id': topic_id,
                'page': page,
                'distribute_time': None,
                'complete_time': None,
                'type': '403_retry',
            })

        if 'post' in i['error']:
            print('post')
            await db.error.delete_one({'_id': i['_id']})
            await db.task.insert_one({
                'id': topic_id,
                'page': page,
                'distribute_time': None,
                'complete_time': None,
                'type': 'post_retry',
            })

        if 'get' in i['error']:
            print('get')
            await db.error.delete_one({'_id': i['_id']})
            await db.task.insert_one({
                'id': topic_id,
                'page': page,
                'distribute_time': None,
                'complete_time': None,
                'type': 'get_retry',
            })

        if 'null' in i['error']:
            print('null')
            await db.error.delete_one({'_id': i['_id']})
            await db.task.insert_one({
                'id': topic_id,
                'page': page,
                'distribute_time': None,
                'complete_time': None,
                'type': 'null_retry',
            })

asyncio.run(check_index())
