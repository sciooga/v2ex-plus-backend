import asyncio
import motor.motor_asyncio
# 按顺序遍历 id 找出缺失的主题
async def check_index():
    client = motor.motor_asyncio.AsyncIOMotorClient('mongodb://mongo')
    db = client['V2EX']
    collection = db['topic']
    # 已经遍历过一次了，后面只需要从 92 万开始
    cursor = collection.find({'id': {'get': 900000}}, {'id': 1}).sort('id', 1)
    prev_index = None
    async for document in cursor:
        index = document.get('id')
        if not index % 1000:
            print(index)
        if prev_index is not None and index != prev_index + 1:
            for missing_index in range(prev_index + 1, index):
                print(f'Missing index: {missing_index}')
                db.task.insert
                await db.task.insert_one({
                    'id': missing_index,
                    'page': 1,
                    'distribute_time': None,
                    'complete_time': None,
                    'type': 'miss',
                })
        prev_index = index

asyncio.run(check_index())
