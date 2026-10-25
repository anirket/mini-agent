MAX_TOKENS = 6_000
SYSTEM_PROMPT = 'You are a helpful assistant'
MODEL = {
    "id": "claude-sonnet-5-5",
    "cost" :{
        'in': 2,
        'out': 10
    }
}
MAX_STEPS = 8
USD_INR_CONVERSION_RATE = 100 # base 100 conversion 1 dollar = Rs. 100
BUDGET = 60_000


HISTORY_CEILING = 12_000   # summarise older turns once history (messages) goes over this
KEEP_LAST = 4              # messages kept word for word after a summary (keep it even)
