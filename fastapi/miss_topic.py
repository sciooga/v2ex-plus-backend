import asyncio
from database import db

# 按顺序遍历 id 找出缺失的主题
async def check_id():
    # 已经遍历过一次了，后面只需要从 92 万开始
    cursor = db.topic.find({'id': {'get': 900000}}, {'id': 1}).sort('id', 1)
    prev_index = None
    async for document in cursor:
        index = document.get('id')
        if prev_index is not None and index != prev_index + 1:
            for missing_index in range(prev_index + 1, index):
                print(f'遗漏主题: {missing_index}')
                await db.task.insert_one({
                    'id': missing_index,
                    'page': 1,
                    'distribute_time': None,
                    'complete_time': None,
                    'type': 'miss',
                })
        prev_index = index

asyncio.run(check_id())
