```sh
cp .env.example .env # set ROBOFLOW_API_KEY and OPENAI_API_KEY

# run server with env loaded
uv run --env-file .env fastapi dev main.py --host 0.0.0.0

# type check, lint, and format
uv run ty check && uv run ruff check --fix && uv run ruff format

# use Python like this:
uv run -- python foo.py

# you can add package like this:
uv add package_name
```
