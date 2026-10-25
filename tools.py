from pydantic import BaseModel, Field
from typing import Literal
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup
from pathlib import Path

WORKSPACE = Path(__file__).parent / 'workspace'
MAX_FILE_CHARS = 8000

allowed_expression = Literal['+', '-', '*', '/', '**', '%']

class calculate_input(BaseModel):
    first_input: float = Field(..., description="The first input of caluclate function")
    second_input: float = Field(..., description="The second input of caluclate function")
    expression: allowed_expression = Field(..., description="The expression which is to be perfomed on the two inputs provided")

class fetch_url_input(BaseModel):
    url: str = Field(..., description="The url whose text needs to be extracted")

class read_file_input(BaseModel):
    file_name: str = Field(..., description="Name of the file whose contents need to be fetched")

# Errors are raised, not returned: execute_tool catches them and sets is_error=True
def calculate(first_input: float, second_input: float, expression: allowed_expression) -> float:
    if expression == '+':
        return first_input + second_input
    elif expression == '-':
        return first_input - second_input
    elif expression == '*':
        return first_input * second_input
    elif expression == '/':
        return first_input / second_input
    elif expression == '**':
        return first_input ** second_input
    elif expression == '%':
        return first_input % second_input
    raise ValueError(f"Not a valid expression. Allowed: {allowed_expression}")


def fetch_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError('Only HTTP or HTTPS urls allowed')
    response = httpx.get(url, timeout=10.0, follow_redirects=True,
                         headers={'User-Agent': 'mini-agent/0.1 (learning project)'})
    response.raise_for_status()   # 404 / timeout raise httpx errors; execute_tool catches them
    soup = BeautifulSoup(response.text, 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    return soup.get_text(' ', strip=True)[:8000]


def read_file(file_name: str) -> str:
    workspace_path = WORKSPACE.resolve()
    file = (workspace_path / file_name).resolve()

    if not file.is_relative_to(workspace_path):
        raise ValueError("path outside workspace")

    if file.suffix.lower() != '.txt':
        raise ValueError(f"Invalid file Type: {file.suffix}. Only .txt files are allowed")

    with open(file, 'r') as f:
        return f.read(MAX_FILE_CHARS)


all_tools = [
    {
        'name': 'calculate',
        'description': 'caluclation of two inputs: Allowed expression: +, -, *, /, **,  or % which is to be perfomed on the two inputs provided. % is remainder (modulo), not percent: for "15% of 200" use 200 * 0.15',
        'input_schema': calculate_input.model_json_schema()
    },
    {
        'name': 'fetch_url',
        'description': 'Allows fetching content of any http or https URL and provides its visible text (HTML tags removed), cut to the first 8000 characters',
        'input_schema': fetch_url_input.model_json_schema()
    },
    {
        'name': 'read_file',
        'description': 'Allows reading a local .txt file present in workspace folder and returns its content (first 8000 characters). Only .txt files are allowed; pass the file name, e.g. "email.txt"',
        'input_schema': read_file_input.model_json_schema()
    }
]


