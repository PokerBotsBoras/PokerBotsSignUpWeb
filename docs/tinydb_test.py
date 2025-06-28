from tinydb import TinyDB
from datetime import datetime, timedelta
import random

# Use the same path as your app
DB_PATH = 'results.json'
db = TinyDB(DB_PATH)

# Simulate appending several results
def make_result(idx):
    base_date = datetime(2025, 6, 28, 12, 0, 0)
    date_str = (base_date + timedelta(hours=idx)).isoformat() + 'Z'
    results = [
        {
            'BotA': f'Bot_{random.randint(1,5)}',
            'BotB': f'Bot_{random.randint(6,10)}',
            'BotAWins': random.randint(0, 10),
            'BotBWins': random.randint(0, 10)
        }
        for _ in range(3)
    ]
    return {
        'Date': date_str,
        'Results': results
    }

for i in range(5):
    db.insert(make_result(i))

print('Inserted 5 test results. Check results.json!')
print(f'Total entries in db: {len(db)}')
